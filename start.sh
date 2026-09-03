#!/bin/bash
# Manually start the PIB crawler, detached so it survives this terminal closing.
#
#   ./start.sh              # checks PIB is healthy first, then starts
#   ./start.sh --force      # start even if PIB looks sick
#   ./start.sh --rate 3 --max-rate 6     # override pacing
#
# Stop with:  ./stop.sh     (or: pkill -INT -f "crawl.py --db corpus.db")

cd "$(dirname "$0")" || exit 1

RATE=5
MAX_RATE=10
RAMP=300
FORCE=0
while [ $# -gt 0 ]; do
  case "$1" in
    --force)    FORCE=1; shift ;;
    --rate)     RATE=$2; shift 2 ;;
    --max-rate) MAX_RATE=$2; shift 2 ;;
    --ramp)     RAMP=$2; shift 2 ;;
    *) echo "unknown option: $1"; exit 1 ;;
  esac
done

if pgrep -f "crawl.py --db corpus.db" >/dev/null; then
  echo "already running (pid $(pgrep -f 'crawl.py --db corpus.db' | head -1))"
  exit 0
fi

if [ "$FORCE" -eq 0 ]; then
  echo -n "checking PIB health... "
  probe=$(curl -s -o /dev/null --max-time 20 -A 'Mozilla/5.0 Chrome/120.0' \
            -w '%{http_code} %{time_total}' \
            "https://archive.pib.gov.in/archive2/PrintRelease.aspx?relid=100000" 2>/dev/null)
  code=${probe%% *}; secs=${probe##* }
  ms=$(echo "$secs * 1000 / 1" | bc 2>/dev/null || echo 99999)
  echo "code=$code latency=${ms}ms"
  case "$code" in
    200|302) ;;
    *) echo "PIB unreachable — not starting. Use --force to override."; exit 1 ;;
  esac
  if [ "${ms:-99999}" -ge 3000 ]; then
    echo "PIB is responding but DEGRADED (${ms}ms; healthy is <100ms)."
    echo "Crawling now risks recording real releases as absent. Use --force to override."
    exit 1
  fi
fi

nohup caffeinate -is python3 -u crawl.py --db corpus.db \
      --rate "$RATE" --max-rate "$MAX_RATE" --ramp-after-sec "$RAMP" \
      >> crawl.log 2>&1 &
disown
sleep 6

if pgrep -f "crawl.py --db corpus.db" >/dev/null; then
  echo "started (pid $(pgrep -f 'crawl.py --db corpus.db' | head -1)), rate ${RATE}->${MAX_RATE} req/s"
  tail -1 crawl.log
else
  echo "FAILED to start — check crawl.log"; tail -5 crawl.log; exit 1
fi
