#!/usr/bin/env python3
"""
Snapshot the full keyword review into corpus.db as a permanent audit record.

Every word we ever ruled on — kept or dropped, in any sweep — with the numbers
that were in front of us when we decided. This consolidates what is currently
split across two places (the decision lives in `terms`, the supporting metrics
live in the `candidate_runs` scratch) into one durable table, so the scratch can
later be deleted without losing the provenance.
"""
import os, sqlite3

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "corpus.db")

# which committed round came from which filter run (for pulling the metrics)
ROUND_RUN = {2: "patch-v2-2024-2026", 3: "sweep2-2024-2026"}
ROUND_SWEEP = {0: "seed (K1)", 1: "prior review", 2: "sweep 1", 3: "sweep 2"}

con = sqlite3.connect(DB, timeout=60)
con.execute("DROP TABLE IF EXISTS keyword_review")
con.execute("""
    CREATE TABLE keyword_review (
        term           TEXT PRIMARY KEY,
        decision       TEXT,      -- keep | drop
        status         TEXT,      -- accepted | rejected (same call, terms wording)
        round          INTEGER,   -- 0 seed, 1 prior, 2 sweep 1, 3 sweep 2
        sweep          TEXT,      -- human-readable version of round
        channel        TEXT,      -- named system | AI-shaped | phrase | seed | human
        ai_releases    INTEGER,   -- releases where the word appears AND are AI
        total_releases INTEGER,   -- all releases the word appears in
        share          REAL,      -- ai_releases / total_releases
        redundant      INTEGER,   -- 1 = contains a word we already had
        reviewed_by    TEXT,
        reviewed_at    TEXT
    )""")

rows = con.execute(
    "SELECT term, round, status, reviewed_by, reviewed_at, channel "
    "FROM terms WHERE status IN ('accepted','rejected')").fetchall()

n = 0
for term, rnd, status, rby, rat, term_ch in rows:
    decision = "keep" if status == "accepted" else "drop"
    sweep = ROUND_SWEEP.get(rnd, "round %s" % rnd)
    run = ROUND_RUN.get(rnd)
    ch, inp, tot, sh, red = term_ch, None, None, None, None
    if run:
        m = con.execute(
            "SELECT channel, in_pool, total, share, redundant "
            "FROM candidate_runs WHERE run_label=? AND term=?", (run, term)).fetchone()
        if m:
            ch = m[0] or term_ch
            inp, tot, sh, red = m[1], m[2], m[3], m[4]
    con.execute("INSERT OR REPLACE INTO keyword_review VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (term, decision, status, rnd, sweep, ch, inp, tot, sh, red, rby, rat))
    n += 1

con.execute("CREATE INDEX ix_kr_decision ON keyword_review(decision)")
con.execute("CREATE INDEX ix_kr_sweep ON keyword_review(sweep)")
con.commit()
con.execute("PRAGMA wal_checkpoint(TRUNCATE)")

print("keyword_review written: %d words" % n)
print("\nby sweep and decision:")
for sw, dec, c in con.execute(
        "SELECT sweep, decision, COUNT(*) FROM keyword_review GROUP BY sweep, decision ORDER BY round, decision"):
    print("  %-14s %-5s %5d" % (sw, dec, c))
print("\nsample kept words with their numbers:")
for r in con.execute("SELECT term, sweep, channel, ai_releases, total_releases, "
                     "CAST(share*100 AS INT)||'%' FROM keyword_review "
                     "WHERE decision='keep' AND ai_releases IS NOT NULL "
                     "ORDER BY ai_releases DESC LIMIT 8"):
    print("  %-26s %-8s %-13s %4s/%-4s %s" % r)
con.close()
