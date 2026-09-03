#!/usr/bin/env python3
"""
Dataset + crawl status.  Run any time, whether or not the crawler is going.

    python3 status.py            # summary
    python3 status.py --years    # add per-year breakdown
    python3 status.py --ministries
    python3 status.py --all
"""
import argparse
import os
import re
import sqlite3
import subprocess
import sys
import time

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "corpus.db")
LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "crawl.log")
TOTAL = 292729                      # full relid space
BAR = 46


def q1(con, sql, default=0):
    r = con.execute(sql).fetchone()
    return (r[0] if r and r[0] is not None else default)


def human(n):
    return "{:,}".format(n)


def bar(frac):
    fill = int(round(frac * BAR))
    return "[" + "#" * fill + "." * (BAR - fill) + "]"


def crawler_running():
    try:
        out = subprocess.run(["pgrep", "-f", "crawl.py --db corpus.db"],
                             capture_output=True, text=True)
        return out.returncode == 0
    except Exception:
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", action="store_true")
    ap.add_argument("--ministries", action="store_true")
    ap.add_argument("--all", action="store_true")
    a = ap.parse_args()
    if a.all:
        a.years = a.ministries = True

    if not os.path.exists(DB):
        sys.exit("no database at %s" % DB)
    con = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)

    attempted = q1(con, "SELECT COUNT(*) FROM fetch_log")
    stored    = q1(con, "SELECT COUNT(*) FROM releases")
    absent    = q1(con, "SELECT COUNT(*) FROM fetch_log WHERE parse_status='absent'")
    partial   = q1(con, "SELECT COUNT(*) FROM fetch_log WHERE parse_status='partial'")
    failed    = q1(con, "SELECT COUNT(*) FROM fetch_log WHERE parse_status='failed'")
    terr      = q1(con, "SELECT COUNT(*) FROM fetch_log WHERE http_status IS NULL")
    # A 'partial' with an empty body is a genuinely title-only PIB release (a
    # one-line headline with no paragraph) — verified by re-fetching. That is
    # correctly recorded, not a defect, so it should not raise the review flag.
    # A 'partial' that still has body text WOULD mean we lost content, so those
    # stay flagged.
    partial_empty = q1(con, "SELECT COUNT(*) FROM fetch_log f "
                            "JOIN releases r ON r.relid=f.relid "
                            "WHERE f.parse_status='partial' "
                            "AND COALESCE(r.word_count,0)=0")
    partial_body  = partial - partial_empty
    frac      = attempted / float(TOTAL)

    running = crawler_running()
    print()
    print("  PIB CORPUS  —  crawler %s" % ("RUNNING" if running else "stopped"))
    print("  " + "-" * 62)
    print("  %s %5.1f%%   %s / %s relids" % (bar(frac), frac * 100,
                                             human(attempted), human(TOTAL)))
    print()
    print("  releases stored   %s" % human(stored))
    print("  absent (302)      %s   (%.1f%% of probed)"
          % (human(absent), 100.0 * absent / max(1, attempted)))
    if partial_empty:
        print("  parse partial     %s   (%s title-only, no body — benign)"
              % (human(partial), human(partial_empty)))
    else:
        print("  parse partial     %s" % human(partial))
    print("  parse failed      %s" % human(failed))
    print("  transport errors  %s" % human(terr))
    review = failed + terr + partial_body
    flag = "clean" if review == 0 else ("NEEDS REVIEW (%d)" % review)
    print("  data quality      %s" % flag)

    # ---- throughput / eta (only meaningful while running)
    recent = q1(con, "SELECT COUNT(*) FROM fetch_log WHERE fetched_at > "
                     "strftime('%Y-%m-%dT%H:%M:%S','now','-300 seconds')")
    if recent:
        rate = recent / 300.0
        left = TOTAL - attempted
        eta_h = left / rate / 3600.0
        fin = time.strftime("%a %H:%M", time.localtime(time.time() + left / rate))
        print()
        print("  throughput        %.2f req/s  (last 5 min)" % rate)
        print("  remaining         %s relids" % human(left))
        print("  eta               %.1f h  ->  %s" % (eta_h, fin))

    # ---- coverage frontier
    lo = q1(con, "SELECT MIN(relid) FROM fetch_log", None)
    hi = q1(con, "SELECT MAX(relid) FROM fetch_log", None)
    d0 = q1(con, "SELECT MIN(release_date) FROM releases", None)
    d1 = q1(con, "SELECT MAX(release_date) FROM releases", None)
    print()
    print("  relid range       %s .. %s" % (lo, hi))
    print("  date range        %s .. %s" % (d0, d1))
    ndates = q1(con, "SELECT COUNT(DISTINCT release_date) FROM releases")
    print("  distinct dates    %s" % human(ndates))

    # ---- storage
    size = os.path.getsize(DB) / (1024.0 ** 3)
    per = (os.path.getsize(DB) / stored / 1024.0) if stored else 0
    print()
    print("  database          %.2f GB   (%.1f KB/release)" % (size, per))
    if stored and attempted < TOTAL:
        proj = os.path.getsize(DB) / float(attempted) * TOTAL / (1024.0 ** 3)
        print("  projected final   %.2f GB" % proj)

    # ---- governor events
    if os.path.exists(LOG):
        ev = [l.strip() for l in open(LOG, errors="replace") if "[gov]" in l]
        if ev:
            print()
            print("  rate-governor events (last 5 of %d)" % len(ev))
            for l in ev[-5:]:
                print("    " + re.sub(r"^\s*\[gov\]\s*", "", l))

    # ---- optional breakdowns
    if a.years:
        print()
        print("  releases per year")
        rows = con.execute(
            "SELECT substr(release_date,1,4) y, COUNT(*) n FROM releases "
            "WHERE release_date IS NOT NULL GROUP BY y ORDER BY y").fetchall()
        mx = max([r[1] for r in rows]) if rows else 1
        for y, n in rows:
            print("    %s  %6s  %s" % (y, human(n), "#" * int(34.0 * n / mx)))

    if a.ministries:
        print()
        print("  top ministries")
        for m, n in con.execute(
                "SELECT ministry_raw, COUNT(*) n FROM releases "
                "GROUP BY 1 ORDER BY n DESC LIMIT 15"):
            print("    %6s  %s" % (human(n), (m or "(none)")[:52]))

    print()
    con.close()


if __name__ == "__main__":
    main()
