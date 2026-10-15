// The GitHub Pages copy of this site is a frozen snapshot built by
// scripts/build_static_demo.py with NEXT_PUBLIC_STATIC_DEMO=1. In the normal live build both
// values below are inert (false and an empty string), so none of the snapshot wording appears.
//
// A snapshot must not claim to be live, must not link to routes it does not contain (the
// passcode-gated /private/*), and must not show "age" figures computed at build time, which
// would read as stale the moment they were published.

export const STATIC_DEMO = process.env.NEXT_PUBLIC_STATIC_DEMO === "1";
export const SNAPSHOT_LABEL = process.env.NEXT_PUBLIC_SNAPSHOT_LABEL ?? "";
export const REPO_URL = "https://github.com/aaaaaron29/pa-grid-monitor";
