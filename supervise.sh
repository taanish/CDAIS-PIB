#!/bin/bash
# PIB crawl supervisor.
#
# Watches the crawler and notifies you (macOS notification + log) whenever the
# state changes. If PIB goes unreachable it waits, probing gently, and restarts
# the crawl automatically when the host comes back.
#
#   ./supervise.sh &          # or: nohup ./supervise.sh >/dev/null 2>&1 &
#
# Stop with:  pkill -f supervise.sh

cd "$(dirname "$0")" || exit 1
DB=corpus.db
LOG=supervisor.log
CRAWL_ARGS="--db corpus.db --rate 5 --max-rate 10 --ramp-after-sec 300"
PROBE_URL="https://archive.pib.gov.in/archive2/PrintRelease.aspx?relid=100000"
TOTAL=292729

CHECK_EVERY=60         # seconds between health checks while running
PROBE_EVERY=600        # seconds between reachability probes while host is down
STALL_AFTER=300        # seconds with no new rows before we call it stalled

state=""               # running | stalled | down | complete

note () {              # note <title> <message>
  local ts; ts=$(date "+%Y-%m-%d %H:%M:%S")
  echo "$ts  $1 — $2" >> "$LOG"
  osascript -e "display notification \"$2\" with title \"PIB crawl: $1\"" 2>/dev/null
}

set_state () {         # only notify on an actual transition
  [ "$state" = "$1" ] && return
  state="$1"; note "$1" "$2"
}

rows ()      { sqlite3 "$DB" 'SELECT COUNT(*) FROM fetch_log;' 2>/dev/null || echo 0; }
alive ()     { pgrep -f "crawl.py --db corpus.db" >/dev/null; }
# "Reachable" must mean healthy enough to be worth crawling, not merely alive.
# PIB has been answering in 15s during degradation — that is up, but at 4
# requests/minute it is useless, so treat it as down and wait.
HEALTHY_MS=3000
reachable () {
  local out code ms
  out=$(curl -s -o /dev/null --max-time 20 -A 'Mozilla/5.0 Chrome/120.0' \
          -w '%{http_code} %{time_total}' "$PROBE_URL" 2>/dev/null) || return 1
  code=${out%% *}; ms=$(echo "${out##* } * 1000 / 1" | bc 2>/dev/null || echo 99999)
  case "$code" in 200|302) ;; *) return 1 ;; esac
  [ "${ms:-99999}" -lt "$HEALTHY_MS" ]
}

start_crawl () {
  nohup caffeinate -is python3 -u crawl.py $CRAWL_ARGS >> crawl.log 2>&1 &
  disown
  sleep 8
}

note "supervisor started" "watching $DB"
last_rows=$(rows); last_change=$(date +%s)

while true; do
  now=$(date +%s); cur=$(rows)

  # finished?
  if [ "$cur" -ge "$TOTAL" ]; then
    set_state complete "all $TOTAL relids probed — crawl finished"
    sleep "$CHECK_EVERY"; continue
  fi

  if [ "$cur" -gt "$last_rows" ]; then          # progress since last check
    last_rows=$cur; last_change=$now
    pct=$(( cur * 100 / TOTAL ))
    set_state running "advancing — ${cur} / ${TOTAL} (${pct}%)"
    sleep "$CHECK_EVERY"; continue
  fi

  stalled_for=$(( now - last_change ))
  [ "$stalled_for" -lt "$STALL_AFTER" ] && { sleep "$CHECK_EVERY"; continue; }

  # No progress for a while. Is the host up or are we the problem?
  if reachable; then
    if alive; then
      set_state stalled "no new rows for $((stalled_for/60))m but PIB responds — check crawl.log"
      sleep "$CHECK_EVERY"
    else
      note "restarting" "PIB reachable and crawler not running — resuming"
      start_crawl
      state=""; last_change=$(date +%s)
    fi
  else
    set_state down "PIB unreachable — crawl paused, probing every $((PROBE_EVERY/60))m"
    alive && pkill -INT -f "crawl.py --db corpus.db"    # don't hammer a dead host
    sleep "$PROBE_EVERY"
  fi
done
