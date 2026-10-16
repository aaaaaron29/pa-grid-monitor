# Running the pipeline on a VPS

Everything the pipeline needs runs on one small server (4 GB RAM, 2 vCPUs is enough) with
Docker Compose. The website stays on Vercel and Neon, so the server only makes outbound calls
and nothing is published to the internet except SSH.

| File | Purpose |
|---|---|
| `docker-compose.yml` | Postgres, Kafka, six pollers and consumers, two inference services, and a tools-only `ops` image for one-off jobs |
| `Dockerfile.ops` | Image for the Neon sync, the gap heal and the freshness check |
| `ops.sh` | Cron jobs: `watch` (every 5 min), `sync` (hourly), `heal` (daily), `status` |
| `crontab.example` | The three cron lines |
| `bootstrap.sh` | One-time server setup: Docker, firewall, fail2ban, updates, swap, key-only SSH |
| `.env.example` | The secrets the server needs |

## Why not just `docker-compose.yml` at the repo root

That file is for local development. It publishes Postgres, Kafka and Grafana to the host, and
Docker publishes ports around the host firewall, so on a server that would put them on the
internet. This one publishes nothing. It also adds restart policies, log rotation, data
volumes and a shared throttle volume.

The throttle volume is not optional. PJM allows 6 requests a minute per key, and the clients
enforce that with a lock file in the temp directory shared by every process on the host. Each
container has its own `/tmp`, so without a shared one the LMP poller, the load poller and the
heal job would each think they had the whole allowance and PJM would start answering 429. Every
container that calls PJM sets `TMPDIR` to the shared volume.

## Setting up a new server

1. Create the server (Ubuntu LTS) and put your SSH public key in `/root/.ssh/authorized_keys`.
2. `scp deploy/vps/bootstrap.sh root@SERVER:` and run it as root.
3. `git clone https://github.com/aaaaaron29/pa-grid-monitor /opt/pa-grid-monitor`
4. Copy the model artifacts, which are never in git and never in a public image:
   `scp -r artifacts root@SERVER:/opt/pa-grid-monitor/`
5. Create `deploy/vps/.env` from `.env.example`. Generate `POSTGRES_PASSWORD` on the server
   (`openssl rand -base64 32`) and copy the API keys and the Neon direct URL in without
   echoing them anywhere.
6. `cd /opt/pa-grid-monitor/deploy/vps && docker compose build`

## Moving the running pipeline over (cutover)

Only one machine may poll PJM with the key at a time, so stop the old one first. The live PJM
feed returns only the newest interval, and the verified feed behind it reaches back about six
months, so the existing history is carried across with a dump rather than re-fetched.

1. On the old machine, stop the pollers and consumers (on Windows, uninstall the watchdog with
   `scripts\windows\install_watchdog.ps1 -Uninstall` first so it does not restart them), then
   take the dump: `pg_dump -Fc -f pjm_grid_watch.dump <database>`. Copy it to the server.
2. On the server, start only Postgres and restore:
   `docker compose up -d postgres`, then
   `docker compose exec -T postgres pg_restore -U pjm_grid_watch -d pjm_grid_watch --clean --if-exists < pjm_grid_watch.dump`
3. `docker compose up -d`, then `crontab crontab.example` (edit the path if needed).
4. Run `./ops.sh heal` once, which fills the hours between the dump and the first poll from the
   verified feeds. Then `./ops.sh status`.
5. Disable the old machine's Neon sync task (`pa-grid-monitor-neon-sync`) so two machines do not
   both write to Neon. The server's hourly `ops.sh sync` takes over; it continues from Neon's
   newest row, so nothing is re-sent.

## Alerts

`ops.sh watch` writes problems to `/var/log/pa-grid-monitor/ops.log`. Two optional settings in
`.env` make them reach you:

- `NTFY_TOPIC`: a phone push through ntfy.sh. Pick a long random topic name.
- `HEARTBEAT_URL`: a healthchecks.io check URL, pinged after every clean pass. This is the only
  alert that fires if the server itself dies, because it is the pings stopping that raises it.

## Day to day

- `./ops.sh status` shows the containers, how old each data stream is, and open alerts. The
  same picture is on the website at `/private/pipeline`, from a report the hourly sync writes
  to Neon.
- `docker compose logs -f pjm-poller` follows one service.
- Updating: `git pull && docker compose build && docker compose up -d`.
- Everything on the box can be rebuilt from this repo, the artifacts and `.env`. The data is
  also in Neon.
