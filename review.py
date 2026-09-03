#!/usr/bin/env python3
"""
Flip through candidate words one at a time and keep or drop each with a
single keypress. Saves after every key, so you can quit and resume without
losing anything.

    python3 review.py            # start / resume reviewing
    python3 review.py --group named   # only named systems (or: shaped / phrase)

keys:   y = keep    n = drop    s = skip (decide later)
        b = back (revisit the previous one)    q = save & quit

Decisions are written to the review_decisions table in corpus.db as you go.
When you are done, run  apply_review.py --commit  to fold the kept words into
the search list. Nothing is deleted; drops are recorded, not erased.
"""
import argparse
import csv
import os
import sqlite3
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
# Decisions go into a tiny dedicated file, NOT the 831 MB corpus.db. Committing
# a keypress into corpus.db triggers a write-ahead-log checkpoint that can stall
# for 10+ seconds; a small separate database commits in about a millisecond.
DB = os.path.join(HERE, "reviews.db")
SHEET = os.path.join(HERE, "review_candidates.csv")

BOLD = "\033[1m"; DIM = "\033[2m"; GRN = "\033[32m"; RED = "\033[31m"
YEL = "\033[33m"; CLR = "\033[0m"; HOME = "\033[2J\033[H"


def getch():
    """One keypress, no Enter. Unix terminals only."""
    import termios, tty
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
    return ch


def ensure_table(con):
    con.execute("""CREATE TABLE IF NOT EXISTS review_decisions (
                     term TEXT PRIMARY KEY, decision TEXT, decided_at TEXT)""")
    con.commit()


def load_sheet(path, group):
    rows = []
    with open(path) as f:
        for r in csv.DictReader(f):
            g = r["group"]
            if group and group not in g.lower():
                continue
            rows.append(r)
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--group", help="named / shaped / phrase (default: all)")
    ap.add_argument("--reconsider", action="store_true",
                    help="second pass over the flagged list; shows your current "
                         "choice as default, 's' keeps it")
    ap.add_argument("--sheet", help="path to a specific review CSV to work through")
    a = ap.parse_args()

    if a.sheet:
        sheet = a.sheet if os.path.isabs(a.sheet) else os.path.join(HERE, a.sheet)
    elif a.reconsider:
        sheet = os.path.join(HERE, "reconsider_candidates.csv")
    else:
        sheet = SHEET
    if not os.path.exists(sheet):
        sys.exit("no sheet — run %s first" %
                 ("build_reconsider.py" if a.reconsider else "build_review.py"))
    if not sys.stdin.isatty():
        sys.exit("run this in a real terminal (it reads single keypresses).")

    con = sqlite3.connect(DB, timeout=60)
    ensure_table(con)
    # pull any decisions already made (from a previous run, or typed in the CSV)
    decided = {r[0]: r[1] for r in con.execute(
        "SELECT term, decision FROM review_decisions")}
    items = load_sheet(sheet, (a.group or "").lower())
    # fold in decisions typed straight into a fresh sheet (not in reconsider
    # mode, where the DECISION column just mirrors the existing choice)
    if not a.reconsider:
        for r in items:
            d = (r["DECISION (keep/drop)"] or "").strip().lower()
            if d in ("keep", "drop") and r["term"] not in decided:
                decided[r["term"]] = d
                con.execute("INSERT OR REPLACE INTO review_decisions VALUES (?,?,?)",
                            (r["term"], d, datetime.now(timezone.utc).isoformat()))
        con.commit()

    total = len(items)
    item_terms = [r["term"] for r in items]
    i = 0
    force = False
    while i < total:
        r = items[i]
        term = r["term"]
        # normal mode skips anything already decided; reconsider mode shows
        # every flagged item so you can change your mind.
        if term in decided and not force and not a.reconsider:
            i += 1
            continue
        force = False
        kept = sum(1 for t in item_terms if decided.get(t) == "keep")
        dropped = sum(1 for t in item_terms if decided.get(t) == "drop")
        done = kept + dropped
        sys.stdout.write(HOME)
        print("%s[ %d of %d reviewed ]%s   %skeep %d%s · %sdrop %d%s · %d left"
              % (DIM, done, total, CLR, GRN, kept, CLR, RED, dropped, CLR, total - done))
        print("%sgroup: %s%s\n" % (DIM, r["group"], CLR))
        cur = decided.get(term)
        tag = ""
        if cur:
            tag = "  %s(currently: %s)%s" % (YEL, cur, CLR)
        print("   %s%s%s%s" % (BOLD, term, CLR, tag))
        print("   %s%s  ·  in %s of %s releases (%s AI)%s"
              % (DIM, r["type"], r["ai_releases"], r["total_releases"], r["pct_ai"], CLR))
        ex = r["example_sentence"].strip()
        if ex:
            print("\n   %s“%s”%s" % (DIM, ex, CLR))
        print("\n   %sy%s keep   %sn%s drop   s skip   b back   q quit"
              % (GRN, CLR, RED, CLR))
        try:
            ch = getch().lower()
        except KeyboardInterrupt:
            break
        now = datetime.now(timezone.utc).isoformat()
        if ch in ("y", "k"):
            decided[term] = "keep"
            con.execute("INSERT OR REPLACE INTO review_decisions VALUES (?,?,?)", (term, "keep", now))
            con.commit(); i += 1
        elif ch in ("n", "d"):
            decided[term] = "drop"
            con.execute("INSERT OR REPLACE INTO review_decisions VALUES (?,?,?)", (term, "drop", now))
            con.commit(); i += 1
        elif ch == "s":
            i += 1
        elif ch == "b":
            i = max(0, i - 1); force = True
        elif ch in ("q", "\x03", "\x04"):
            break

    kept = sum(1 for t in item_terms if decided.get(t) == "keep")
    dropped = sum(1 for t in item_terms if decided.get(t) == "drop")
    sys.stdout.write(HOME)
    print("stopped. %skeep %d%s · %sdrop %d%s · %d of %d still undecided"
          % (GRN, kept, CLR, RED, dropped, CLR, total - kept - dropped, total))
    print("\nresume any time:   python3 review.py")
    print("commit the keeps:  python3 apply_review.py --commit")
    con.close()


if __name__ == "__main__":
    main()
