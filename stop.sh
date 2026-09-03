#!/bin/bash
# Stop the crawler cleanly. The in-flight batch is committed, not discarded.
#   ./stop.sh            stop the crawler
#   ./stop.sh --all      also stop the supervisor (full manual control)
cd "$(dirname "$0")" || exit 1
if pgrep -f "crawl.py --db corpus.db" >/dev/null; then
  pkill -INT -f "crawl.py --db corpus.db"; sleep 4; echo "crawler stopped"
else
  echo "crawler was not running"
fi
if [ "$1" = "--all" ]; then
  pkill -f supervise.sh 2>/dev/null && echo "supervisor stopped" || echo "supervisor was not running"
fi
sqlite3 corpus.db "SELECT COUNT(*)||' probed, '||(SELECT COUNT(*) FROM releases)||' releases' FROM fetch_log;"
