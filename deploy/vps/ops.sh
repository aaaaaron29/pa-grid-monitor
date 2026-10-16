#!/usr/bin/env bash
# Host-side jobs for the VPS, run from cron (see deploy/vps/README.md and crontab.example):
#
#   ops.sh watch    every 5 minutes: start what is down, restart what is stuck, alert on stalled
#                   data, ping the dead-man's switch
#   ops.sh sync     hourly: copy new rows to Neon, which the website reads
#   ops.sh heal     daily: re-pull the last few days from the verified feeds and re-score them,
#                   which closes the gaps an outage leaves
#   ops.sh status   print the state by hand
#
# This is the Linux counterpart of scripts/windows/watchdog.ps1 and uses the same limits.

set -uo pipefail
cd "$(dirname "$(readlink -f "$0")")"

STATE_DIR="${STATE_DIR:-/var/lib/pa-grid-monitor}"
LOG_DIR="${LOG_DIR:-/var/log/pa-grid-monitor}"
mkdir -p "$STATE_DIR/alerts" "$LOG_DIR"

REALERT_SECONDS=$((3 * 3600))
NEON_MAX_AGE_SECONDS=$((150 * 60))
HEAL_DAYS=4

# Minutes a stream may go without a new row before it counts as stalled. Normal ages: PJM LMP
# a few minutes, EIA about 2 to 6 hours, PJM metered load 1 to 2 days.
declare -A STALE_MINUTES=(
  [pjm_lmp]=25 [pjm_lmp_scored]=40 [eia_demand]=480 [eia_scored]=540 [pjm_load]=5760
)

compose() { docker compose "$@"; }
now() { date +%s; }
log() { echo "$(date -u '+%Y-%m-%d %H:%M:%S') $*" >> "$LOG_DIR/ops.log"; }

# .env holds URLs with characters a shell would misread, so read single values instead of
# sourcing the file.
env_val() { grep -E "^$1=" .env 2>/dev/null | head -1 | cut -d= -f2- | sed -e "s/^[\"']//" -e "s/[\"']$//"; }
NTFY_TOPIC="$(env_val NTFY_TOPIC)"
HEARTBEAT_URL="$(env_val HEARTBEAT_URL)"

notify() { # title, body
  [ -n "$NTFY_TOPIC" ] || return 0
  curl -fsS -m 15 -H "Title: $1" -d "$2" "https://ntfy.sh/$NTFY_TOPIC" > /dev/null 2>&1 \
    || log "ntfy failed"
}

declare -A PROBLEMS=()
problem() { PROBLEMS["$1"]="$2"; }

alert_file() { echo "$STATE_DIR/alerts/${1//[^A-Za-z0-9_.-]/_}"; }

publish_alerts() {
  local key f last
  for key in "${!PROBLEMS[@]}"; do
    f="$(alert_file "$key")"
    last=0
    [ -f "$f" ] && last="$(cat "$f")"
    if [ $(( $(now) - last )) -ge "$REALERT_SECONDS" ]; then
      log "ALERT [$key] ${PROBLEMS[$key]}"
      notify "PA Grid Monitor: problem" "${PROBLEMS[$key]}"
      now > "$f"
    fi
  done
  for f in "$STATE_DIR"/alerts/*; do
    [ -e "$f" ] || continue
    key="$(basename "$f")"
    if [ -z "${PROBLEMS[$key]+x}" ]; then
      log "RECOVERED [$key]"
      notify "PA Grid Monitor: recovered" "Problem cleared: $key"
      rm -f "$f"
    fi
  done
}

counter_get() { cat "$STATE_DIR/$1" 2>/dev/null || echo 0; }
counter_set() { echo "$2" > "$STATE_DIR/$1"; }

cmd_watch() {
  exec 9> "$STATE_DIR/watch.lock"
  flock -n 9 || exit 0

  # 1. Everything that should be running is. "up -d" starts only what is missing.
  local expected running svc missing=0
  expected="$(compose config --services | grep -vx migrate | sort)"
  running="$(compose ps --status running --services | sort)"
  for svc in $expected; do
    if ! grep -qx "$svc" <<< "$running"; then
      missing=1
      log "$svc is not running"
    fi
  done
  if [ "$missing" -eq 1 ]; then
    log "starting missing services"
    compose up -d >> "$LOG_DIR/ops.log" 2>&1 || problem compose "docker compose up failed. See $LOG_DIR/ops.log."
    sleep 20
    running="$(compose ps --status running --services | sort)"
    for svc in $expected; do
      grep -qx "$svc" <<< "$running" || problem "svc-$svc" "$svc is not running and could not be started."
    done
  fi

  # 2. The two scoring services answer their health check. Three bad checks in a row restart it.
  local health n
  for svc in eia-inference pjm-inference; do
    health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{end}}' "$(compose ps -q "$svc")" 2>/dev/null)"
    if [ "$health" = "unhealthy" ]; then
      n=$(( $(counter_get "health-$svc") + 1 ))
      counter_set "health-$svc" "$n"
      if [ "$n" -ge 3 ]; then
        log "$svc unhealthy for $n checks, restarting"
        compose restart "$svc" >> "$LOG_DIR/ops.log" 2>&1
        counter_set "health-$svc" 0
      else
        problem "health-$svc" "$svc is unhealthy."
      fi
    else
      counter_set "health-$svc" 0
    fi
  done

  # 3. Each data stream is getting new rows.
  local ages key age limit
  ages="$(compose run --rm -T ops python scripts/pipeline_status.py 2>/dev/null | tail -1)"
  if [ -z "$ages" ] || [ "$(jq -r 'has("error")' <<< "$ages" 2>/dev/null)" != "false" ]; then
    problem database "Could not read data freshness from the database: ${ages:-no output}"
  else
    for key in "${!STALE_MINUTES[@]}"; do
      age="$(jq -r ".$key // empty" <<< "$ages")"
      [ -n "$age" ] || continue
      limit="${STALE_MINUTES[$key]}"
      if awk "BEGIN{exit !($age > $limit)}"; then
        problem "stale-$key" "$key has had no new data for ${age%.*} min (limit $limit min)."
      fi
    done
    # LMP stalled while everything claims to be running: restart that chain, at most hourly.
    age="$(jq -r '.pjm_lmp // empty' <<< "$ages")"
    if [ -n "$age" ] && awk "BEGIN{exit !($age > 30)}"; then
      local last_restart
      last_restart="$(counter_get lmp-restart-at)"
      if [ $(( $(now) - last_restart )) -ge 3600 ]; then
        log "pjm LMP data is ${age%.*} min old, restarting the PJM poller, consumer and inference service"
        compose restart pjm-poller pjm-consumer pjm-inference >> "$LOG_DIR/ops.log" 2>&1
        counter_set lmp-restart-at "$(now)"
      fi
    fi
  fi

  # 4. The hourly Neon sync is succeeding (the website only sees what it copies).
  if [ -f "$STATE_DIR/neon_last_ok" ]; then
    local sync_age=$(( $(now) - $(stat -c %Y "$STATE_DIR/neon_last_ok") ))
    [ "$sync_age" -le "$NEON_MAX_AGE_SECONDS" ] \
      || problem neon-sync "The Neon sync has not succeeded for $((sync_age / 60)) min. The website is going stale."
  fi

  publish_alerts
  now > "$STATE_DIR/watch_last"

  # 5. Dead-man's switch: a clean pass pings; a pass with problems pings the fail URL. If the
  # server itself dies the pings simply stop, and the service emails you.
  if [ -n "$HEARTBEAT_URL" ]; then
    if [ "${#PROBLEMS[@]}" -eq 0 ]; then
      curl -fsS -m 15 "$HEARTBEAT_URL" > /dev/null 2>&1 || log "heartbeat ping failed"
    else
      curl -fsS -m 15 "$HEARTBEAT_URL/fail" > /dev/null 2>&1 || true
    fi
  fi
}

# The host's own state as one line of JSON, handed to the Neon sync so the website's pipeline
# page can show it. Names and counts only; nothing secret and no data values.
ops_health_json() {
  local expected running unhealthy alerts
  expected="$(compose config --services | grep -vx migrate | grep -c .)"
  running="$(compose ps --status running --services | grep -c .)"
  unhealthy="$(docker ps --filter health=unhealthy -q | grep -c .)"
  alerts="$(ls "$STATE_DIR/alerts" 2>/dev/null | jq -R . | jq -s .)"
  jq -cn     --argjson expected "${expected:-0}" --argjson running "${running:-0}"     --argjson unhealthy "${unhealthy:-0}" --argjson alerts "${alerts:-[]}"     --argjson watch "$(counter_get watch_last)" --argjson heal "$(counter_get heal_last)"     --argjson heal_days "$HEAL_DAYS"     --argjson uptime "$(cut -d. -f1 /proc/uptime)"     --argjson disk "$(df --output=pcent / | tail -1 | tr -dc 0-9)"     '{services_expected: $expected, services_running: $running, services_unhealthy: $unhealthy,
      open_alerts: $alerts, heal_days: $heal_days, uptime_seconds: $uptime, disk_used_percent: $disk,
      last_watch_at: (if $watch > 0 then ($watch | todate) else null end),
      last_heal_at: (if $heal > 0 then ($heal | todate) else null end)}' 2>/dev/null
}

cmd_sync() {
  exec 8> "$STATE_DIR/sync.lock"
  flock -n 8 || exit 0
  if compose run --rm -T -e "OPS_HEALTH_JSON=$(ops_health_json)" ops python scripts/sync_to_neon.py >> "$LOG_DIR/sync.log" 2>&1; then
    touch "$STATE_DIR/neon_last_ok"
  else
    log "neon sync failed, see $LOG_DIR/sync.log"
  fi
}

cmd_heal() {
  exec 7> "$STATE_DIR/heal.lock"
  flock -n 7 || exit 0
  local start
  start="$(date -u -d "$HEAL_DAYS days ago" +%F)"
  log "gap heal from $start"
  {
    compose run --rm -T ops python -m ingestion.backfill --source pjm --start "$start" --no-metrics-server
    compose run --rm -T ops python -m ingestion.backfill --source eia --start "$start" --no-metrics-server
    compose run --rm -T ops python scripts/rescore_recent.py --days $((HEAL_DAYS + 1))
  } >> "$LOG_DIR/heal.log" 2>&1
  now > "$STATE_DIR/heal_last"
  log "gap heal finished"
}

cmd_status() {
  compose ps
  echo
  compose run --rm -T ops python scripts/pipeline_status.py --pretty
  echo
  echo "Open alerts:"; ls "$STATE_DIR/alerts" 2>/dev/null | sed 's/^/  /'
  [ -f "$STATE_DIR/neon_last_ok" ] && echo "Last Neon sync: $(date -d "@$(stat -c %Y "$STATE_DIR/neon_last_ok")" -u '+%F %T UTC')"
}

case "${1:-}" in
  watch)  cmd_watch ;;
  sync)   cmd_sync ;;
  heal)   cmd_heal ;;
  status) cmd_status ;;
  *) echo "usage: ops.sh watch|sync|heal|status" >&2; exit 2 ;;
esac
