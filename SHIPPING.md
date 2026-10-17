# Shipping checklist

Run through this for every change that gets committed, pushed or deployed. Skip a step only
when it plainly does not apply, and say which one was skipped and why in the hand-off. The
reason this exists: a change is not shipped when it is merged. The code, the docs, the
website, the database schema and the server each ship separately, and any of them can be left
behind.

Everything below was learned the hard way on this project. Where a step has a reason, the
reason is given, because a rule without one gets skipped.

## 0. What kind of change is this?

Decide first, because it sets which sections below apply.

| Change touches | Sections |
|---|---|
| Docs only | 2, 3, 4 |
| Frontend (`frontend/`) | 1, 2, 3, 4, 5a |
| Pipeline code (`common/`, `ingestion/`, `inference/`, `model/`, `scripts/`) | 1, 2, 3, 4, 5c |
| Database schema (`infra/sql/`) | all, and read 5b |
| Kubernetes, Compose or CI files | 1, 2, 3, 4, and expect CI to be the real test |
| Server config or cron (`deploy/vps/`) | 1, 2, 3, 4, 5c |

## 1. Check the work

- [ ] `ruff check .` is clean.
- [ ] `pytest` passes. The integration tests need a reachable Postgres and skip without one,
      so a skip is not a pass. Point `TEST_DATABASE_URL` at a throwaway database when the
      change touches SQL, the sync or the scoring path, and confirm the count of skipped tests.
- [ ] Frontend: `npx tsc --noEmit`, `npm run lint` and `npm run build` in `frontend/`.
- [ ] Frontend UI: look at it in a browser at desktop and phone width, not just the build.
      Use the impeccable plugin for design work, and run its detector once at the end.
- [ ] A bug fix has a test that fails on the old code. Run it against the old code to see it
      fail; a regression test that was never red proves nothing.
- [ ] Verify claims against real data or infrastructure, not assumptions. If something could
      not be checked (no cluster available, no live feed), say so rather than implying it was.
- [ ] No secret in the diff: `git diff --cached` and look for keys, connection strings, the
      passcode, `.env` contents, model artifacts or database dumps.

## 2. Update the docs

Do this before committing, in the same commit as the change, not afterward.

- [ ] **README.md**: does the Status paragraph still tell the truth? Check the route table, the
      "Running it" bullets, the Stack line and any claim about CI or deployment.
- [ ] **ARCHITECTURE.md**: add a dated paragraph in Section 9 for anything that changes how the
      system works or was learned (a finding, a decision, a measured result). Update any
      older paragraph the change makes stale (for example, "not yet running on the VPS").
      Section 10 is only for external dependencies.
- [ ] **deploy/vps/README.md** if the server setup, cron, alerts or runbook changed.
- [ ] **infra/k8s/README.md** and the manifest header comments if manifests changed.
- [ ] Rules for all prose: no em-dashes, no emojis, absolute dates (not "yesterday"), plain
      statements of what was and was not verified, and no raw PJM values, sample rows or
      screenshots anywhere public.
- [ ] Do not describe something as done, deployed or verified until it is. Write the doc
      after the deploy if the deploy is part of the claim.

## 3. Commit

- [ ] Stage files by name; do not `git add -A` blindly. Check `git status` for strays (logs,
      dumps, `.env`, scratch files).
- [ ] A short imperative subject that says what changed and, if it is not obvious, why. One
      logical change per commit.
- [ ] CRLF warnings from git on Windows are harmless.

## 4. Push and watch CI

- [ ] Push to `main`.
- [ ] Watch the CI run to the end. All four jobs have to be green: `lint-and-test`,
      `build-image`, `compose-smoke-test`, `k8s-smoke-test`. The last one now replays a
      synthetic scenario through Kafka, Postgres and the inference service and asserts on
      the result.
- [ ] A red run gets its log read, not a retry. Check whether it is a real failure, a flaky
      test or an environment problem, and say which. Fix forward with a new commit.
- [ ] If the change was risky, one green run is thin evidence. Say so, or get a second.
- [ ] Without the `gh` CLI, poll the Actions API, and read job logs with the GitHub
      credential helper rather than a token pasted anywhere.

## 5. Deploy

Each target ships on its own. Work out which ones this change reaches and do each one.

### a. Website (Vercel)

- [ ] It deploys on push to `main`. Confirm the deploy landed: the public pages return 200 and
      `/private/*` redirects to the login page.
- [ ] Nothing PJM-sourced on a public route. The private pages stay behind the passcode.
- [ ] If the page reads a new table, ship the schema first (5b) or make the page tolerate the
      table being absent.

### b. Database schema (Neon)

- [ ] Migrations are plain SQL in `infra/sql/`, applied to Neon by the server's next hourly
      sync (`scripts/sync_to_neon.py` runs `apply_migrations` first). To apply one at once,
      run `./ops.sh sync` on the server.
- [ ] Migrations must be additive and safe to re-run.
- [ ] Never run anything against Neon by hand that prints its connection string.

### c. The pipeline server (VPS)

The server is `root@169.58.199.180`, key `~/.ssh/pa-grid-vps`, repo at `/opt/pa-grid-monitor`,
stack in `deploy/vps/`. A push does not reach it; only these steps do.

- [ ] `cd /opt/pa-grid-monitor && git pull`
- [ ] `cd deploy/vps && docker compose --profile tools build` (the `ops` image carries the sync
      and heal code, so it needs rebuilding too).
- [ ] `docker compose up -d`. This restarts the pollers, so the live PJM feed misses a minute or
      two that only the next daily heal can fill. Prefer doing it just after a poll.
- [ ] Verify, do not assume: `./ops.sh status`, then wait for a fresh reading and confirm
      `pjm_lmp_scored` is as fresh as `pjm_lmp` (new data is being scored by the new code), and
      grep the last ten minutes of the service logs for errors.
- [ ] Config changes: edit `deploy/vps/.env` or the crontab by hand on the server. Never print
      the contents of `.env`, and never commit it.
- [ ] Run `./ops.sh sync` if the website should see the change now, otherwise the hourly cron does.
- [ ] Rollback is `git checkout <previous commit>` on the server, rebuild, `up -d`.
- [ ] The Windows scheduled tasks stay retired. Do not re-enable `pa-grid-monitor-neon-sync`: two
      machines syncing to Neon would fight.

## 6. After shipping

- [ ] Re-read the docs you wrote in step 2: is each claim now true, including "deployed"?
- [ ] If something was deferred (retraining, a second deploy, a follow-up check), write it where
      it will be found: the ARCHITECTURE open items, not a chat message.
- [ ] Next-day checks worth doing after a pipeline change: `tail /var/log/pa-grid-monitor/ops.log`
      for the 12:15 UTC heal, and `/private/pipeline` for stream ages and completeness.
- [ ] Clean up what the work left running locally: dev servers, throwaway databases and Kafka,
      scratch dumps. Never kill processes by name (`taskkill /IM python.exe` takes down
      everything); kill by port or PID.

## 7. Standing rules

- PJM Data Miner 2 terms forbid redistribution: zone prices and loads appear only behind
  `/private/*`, never on a public page, in the repo, in a screenshot or in a model artifact.
- Never print or paste a Neon connection string, an API key or the live passcode, in output, in
  a file or in a message. If one leaks into output, say so and rotate it.
- Get the owner's review before publishing new data-center list data.
- Ask before anything outward-facing or hard to reverse that was not explicitly requested.

## 8. The hand-off message

End with what was done, what was verified and how, what was not verified, and what is left. Say
plainly when a step above was skipped.
