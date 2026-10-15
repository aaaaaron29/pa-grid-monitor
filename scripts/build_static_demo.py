"""Build the static demo that GitHub Pages serves from docs/.

Run from the repo root:  python scripts/build_static_demo.py

What it does
  1. Copies the frontend into frontend/.static-demo/ (installing its own node_modules from
     the lockfile) WITHOUT the passcode-gated /private/*
     routes, the auth proxy, and the PJM query module. They are left out of the copy, so a
     stray import fails the build loudly instead of leaking.
  2. Builds that copy as a static export (`output: "export"`). Server components run once at
     build time, so the public pages are frozen with the data in the local Postgres at that
     moment. Only the public routes exist: /, /demand, /map.
  3. Scans the output for anything that must never be published (the dev passcode, a database
     URL, the private route names, PJM table names) and aborts if it finds any.
  4. Only then replaces docs/ with the export.

Needs the local Postgres running (the pages read it at build time) and frontend/.env.local
with DATABASE_URL. Only that one variable is copied into the build.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
FRONTEND = REPO / "frontend"
BUILD = FRONTEND / ".static-demo"
DOCS = REPO / "docs"

# Left out of the copy on purpose; see the module docstring.
EXCLUDE = {
    Path("src/app/private"),
    Path("src/proxy.ts"),
    Path("src/lib/auth.ts"),
    Path("src/lib/queries/pjm.ts"),
}

# Strings that must not appear anywhere in the published output.
FORBIDDEN = [
    r"devpasscode",
    r"postgresql://",
    r"DATABASE_URL",
    r"PRIVATE_PASSCODE",
    r"gw_private",
    r"/private/",
    r"pjm_lmp_readings",
    r"pjm_load_readings",
    r"pjm_lmp_anomalies",
    r"Ocp-Apim-Subscription-Key",
]

NEXT_CONFIG = """import type {{ NextConfig }} from "next";

const nextConfig: NextConfig = {{
  output: "export",
  basePath: "{base_path}",
  trailingSlash: true,
  images: {{ unoptimized: true }},
  turbopack: {{
    root: {root},
    rules: {{
      "*.css": {{
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      }},
    }},
  }},
}};

export default nextConfig;
"""


def snapshot_label() -> str:
    now = datetime.now().astimezone()
    offset_hours = now.utcoffset().total_seconds() / 3600 if now.utcoffset() else 0
    names = {-4.0: "EDT", -5.0: "EST", 0.0: "UTC"}
    zone = names.get(offset_hours, "local time")
    return f"{now:%B} {now.day}, {now:%Y}, {now:%I:%M %p}".replace(" 0", " ") + f" {zone}"


def _force_remove(func, path, _exc) -> None:
    """rmtree error handler: Windows refuses to delete read-only files, so clear the flag."""
    os.chmod(path, 0o700)
    func(path)


def remove_build_dir() -> None:
    if BUILD.exists():
        shutil.rmtree(BUILD, onexc=_force_remove)


def install_dependencies() -> None:
    """The workspace installs its own node_modules from the lockfile. Linking the real one in
    does not work: Turbopack rejects a symlink that leaves its root, and the root has to be the
    filtered copy (rooting it at the real frontend/ makes Next find the real proxy.ts)."""
    npm = shutil.which("npm.cmd") or shutil.which("npm") or "npm"
    result = subprocess.run([npm, "ci", "--no-audit", "--no-fund"], cwd=BUILD)
    if result.returncode != 0:
        sys.exit("npm ci failed; docs/ was not touched.")


def copy_frontend() -> None:
    remove_build_dir()
    BUILD.mkdir()
    for name in ("package.json", "package-lock.json", "tsconfig.json", "next-env.d.ts"):
        shutil.copy2(FRONTEND / name, BUILD / name)
    shutil.copytree(FRONTEND / "public", BUILD / "public")

    def ignore(directory: str, names: list[str]) -> list[str]:
        rel = Path(directory).relative_to(FRONTEND)
        return [n for n in names if (rel / n) in EXCLUDE]

    shutil.copytree(FRONTEND / "src", BUILD / "src", ignore=ignore)
    drop_cache_components_export()


def drop_cache_components_export() -> None:
    """The live app enables Cache Components, which cannot be combined with `output: "export"`
    (it implies partial prerendering). The static copy turns it off in next.config, and also
    drops the layout's `export const instant = false`, which exists only for that feature."""
    layout = BUILD / "src" / "app" / "layout.tsx"
    lines = layout.read_text(encoding="utf8").splitlines(keepends=True)
    kept = [ln for ln in lines if ln.strip() != "export const instant = false;"]
    if len(kept) != len(lines) - 1:
        sys.exit("Could not find the layout's `instant` export to remove; the app has changed.")
    layout.write_text("".join(kept), encoding="utf8")


def write_env() -> None:
    env_local = FRONTEND / ".env.local"
    match = re.search(r"^DATABASE_URL=(.+)$", env_local.read_text(encoding="utf8"), re.M)
    if not match:
        sys.exit(
            "frontend/.env.local has no DATABASE_URL; the pages read the database at build time."
        )
    (BUILD / ".env.local").write_text(f"DATABASE_URL={match.group(1)}\n", encoding="utf8")


def run_build(base_path: str, label: str) -> None:
    root = '"' + str(BUILD).replace("\\", "/") + '"'
    (BUILD / "next.config.ts").write_text(
        NEXT_CONFIG.format(base_path=base_path, root=root), encoding="utf8"
    )
    env = {
        **__import__("os").environ,
        "NEXT_PUBLIC_STATIC_DEMO": "1",
        "NEXT_PUBLIC_SNAPSHOT_LABEL": label,
    }
    npx = shutil.which("npx.cmd") or shutil.which("npx") or "npx"
    result = subprocess.run([npx, "next", "build"], cwd=BUILD, env=env)
    if result.returncode != 0:
        sys.exit("next build failed; docs/ was not touched.")


def scan_output(out: Path) -> None:
    problems: list[str] = []
    patterns = [re.compile(p) for p in FORBIDDEN]
    for path in out.rglob("*"):
        if not path.is_file() or path.suffix in {".woff", ".woff2", ".ico", ".png", ".jpg"}:
            continue
        text = path.read_text(encoding="utf8", errors="ignore")
        for pat in patterns:
            if pat.search(text):
                problems.append(f"{path.relative_to(out)}: matches {pat.pattern!r}")
    if problems:
        sys.exit("Refusing to publish; forbidden strings found:\n  " + "\n  ".join(problems[:20]))


def add_dotted_prefetch_aliases(root: Path) -> None:
    """Next 16 exports each route's prefetch payload as `map/__next.map/__PAGE__.txt` but the
    client requests `map/__next.map.__PAGE__.txt`. On a plain static host that is a 404 per
    link (navigation falls back to a full load, so nothing breaks, but the console fills with
    errors). Write a copy at the requested name."""
    for directory in sorted(root.rglob("__next.*")):
        if not directory.is_dir():
            continue
        for payload in directory.glob("*.txt"):
            shutil.copy2(payload, directory.parent / f"{directory.name}.{payload.name}")


def publish(out: Path) -> None:
    for must in ("index.html", "demand/index.html", "map/index.html"):
        if not (out / must).exists():
            sys.exit(f"Export is missing {must}; docs/ was not touched.")
    # Stage the new site next to docs/ and swap it in with renames, so a folder that something
    # is holding open fails the swap while docs/ is still whole, instead of half-deleting it.
    staging = REPO / "docs.new"
    previous = REPO / "docs.old"
    for leftover in (staging, previous):
        if leftover.exists():
            shutil.rmtree(leftover, onexc=_force_remove)
    shutil.copytree(out, staging)
    add_dotted_prefetch_aliases(staging)
    # GitHub Pages runs Jekyll by default, which would drop the _next/ directory.
    (staging / ".nojekyll").write_text("", encoding="utf8")
    if DOCS.exists():
        DOCS.rename(previous)
    staging.rename(DOCS)
    if previous.exists():
        shutil.rmtree(previous, onexc=_force_remove)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-path", default="/pa-grid-monitor", help="Pages sub-path")
    args = parser.parse_args()

    label = snapshot_label()
    print(f"Snapshot label: {label}")
    copy_frontend()
    write_env()
    install_dependencies()
    run_build(args.base_path, label)
    out = BUILD / "out"
    scan_output(out)
    publish(out)
    remove_build_dir()
    print(f"Published {sum(1 for _ in DOCS.rglob('*') if _.is_file())} files to docs/.")


if __name__ == "__main__":
    main()
