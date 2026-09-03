#!/usr/bin/env python3
"""
Fold the review decisions into the search list.

Reads the decisions you made in review.py (stored in the review_decisions
table). Kept words become accepted search terms and join the next round of
searching; dropped words are recorded as rejected so they never resurface.
Nothing is deleted — a dropped word keeps its 'rejected' record, so the whole
review stays auditable and reversible.

    python3 apply_review.py            # show what would change (no writes)
    python3 apply_review.py --commit   # actually write the decisions
"""
import argparse
import os
import sqlite3
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "corpus.db")          # the catalogue (written to)
REVIEWS = os.path.join(HERE, "reviews.db")     # your y/n decisions (read from)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    a = ap.parse_args()

    if not os.path.exists(REVIEWS):
        raise SystemExit("no decisions yet — run review.py first")
    rev = sqlite3.connect("file:%s?mode=ro" % REVIEWS, uri=True)
    keep = [r[0] for r in rev.execute(
        "SELECT term FROM review_decisions WHERE decision='keep'")]
    drop = [r[0] for r in rev.execute(
        "SELECT term FROM review_decisions WHERE decision='drop'")]
    rev.close()
    print("decisions on record: %d keep, %d drop" % (len(keep), len(drop)))

    con = sqlite3.connect(DB, timeout=60)

    # Only commit decisions not already reflected in the term list. Re-committing
    # everything would re-stamp earlier sweeps' words with a new round number and
    # lose which sweep first found them.
    acc = set(r[0] for r in con.execute("SELECT term FROM terms WHERE status='accepted'"))
    rej = set(r[0] for r in con.execute("SELECT term FROM terms WHERE status='rejected'"))
    new_keep = [t for t in keep if t not in acc]
    new_drop = [t for t in drop if t not in rej]
    print("  new this commit: %d keep, %d drop  (rest already on record)"
          % (len(new_keep), len(new_drop)))

    if not a.commit:
        print("\ndry run — nothing written. re-run with --commit to apply.")
        print("first few new keeps: %s" % (", ".join(new_keep[:10]) or "(none)"))
        con.close()
        return

    now = datetime.now(timezone.utc).isoformat()
    nxt = (con.execute("SELECT COALESCE(MAX(round),1) FROM terms "
                       "WHERE status='accepted'").fetchone()[0] or 1) + 1
    for t in new_keep:
        con.execute(
            "INSERT OR REPLACE INTO terms "
            "(term, round, status, reviewed_by, reviewed_at, channel, note) VALUES "
            "(?,?,'accepted','human',?, "
            " (SELECT channel FROM candidate_runs WHERE term=? LIMIT 1), "
            " 'review r%d')" % nxt, (t, nxt, now, t))
        con.execute("UPDATE candidate_runs SET status='accepted' WHERE term=?", (t,))
    for t in new_drop:
        con.execute(
            "INSERT OR REPLACE INTO terms "
            "(term, round, status, reviewed_by, reviewed_at, note) VALUES "
            "(?,?,'rejected','human',?, 'review r%d')" % nxt, (t, nxt, now))
        con.execute("UPDATE candidate_runs SET status='rejected' WHERE term=?", (t,))
    con.commit()
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    con.close()
    print("\ncommitted: %d accepted (round %d), %d rejected." % (len(new_keep), nxt, len(new_drop)))
    print("the kept words are now part of the search list.")


if __name__ == "__main__":
    main()
