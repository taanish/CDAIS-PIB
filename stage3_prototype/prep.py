#!/usr/bin/env python3
"""
Stage-3 prototype prep.

- (Re)creates ai_classifications with a system_seq so one release can carry
  several systems (empty table, safe to recreate), plus type_evidence and
  use_case_given columns to match the rulebook.
- Registers one classification run.
- Pulls the recent slice (release_date >= CUTOFF) and splits the relids into
  N chunk files under this scratch dir, for the subagents to pick up.
"""
import hashlib, os, sqlite3
from datetime import datetime, timezone

HERE   = os.path.dirname(os.path.abspath(__file__))
DB     = "/Users/taanish/Desktop/CDAIS/PIB/corpus.db"
RULES  = "/Users/taanish/Desktop/CDAIS/PIB/rulebook.md"
CUTOFF = "2026-07-01"
NCHUNK = 9
RUN_ID = "proto-2026-07to08-sonnet-r1"
MODEL  = "claude-sonnet-5"

con = sqlite3.connect(DB, timeout=60)

# ---- schema (empty table -> safe recreate) --------------------------------
con.executescript("""
DROP TABLE IF EXISTS ai_classifications;
CREATE TABLE ai_classifications (
    relid              INTEGER REFERENCES releases(relid),
    run_id             TEXT    REFERENCES classification_runs(run_id),
    system_seq         INTEGER NOT NULL DEFAULT 0,
    is_ai_relevant     INTEGER NOT NULL,
    is_substantive     INTEGER NOT NULL,
    mention_type       TEXT,
    type_evidence      TEXT,
    lifecycle_stage    TEXT,
    deploying_body     TEXT,
    system_name        TEXT,
    application_domain TEXT,
    technology_type    TEXT,
    beneficiary_scale  TEXT,
    budget_mentioned   TEXT,
    use_case_given     INTEGER,
    evidence_quote     TEXT,
    evidence_start     INTEGER,
    evidence_end       INTEGER,
    confidence         REAL,
    PRIMARY KEY (relid, run_id, system_seq)
);
CREATE INDEX IF NOT EXISTS ix_aic_run  ON ai_classifications(run_id);
CREATE INDEX IF NOT EXISTS ix_aic_type ON ai_classifications(mention_type);
""")

# ---- slice ----------------------------------------------------------------
relids = [r[0] for r in con.execute(
    "SELECT relid FROM v_ai_pool WHERE release_date >= ? ORDER BY release_date, relid",
    (CUTOFF,))]
n = len(relids)

# ---- run registry ---------------------------------------------------------
sha = hashlib.sha256(open(RULES, "rb").read()).hexdigest()
now = datetime.now(timezone.utc).isoformat()
con.execute("DELETE FROM classification_runs WHERE run_id=?", (RUN_ID,))
con.execute("INSERT INTO classification_runs "
            "(run_id, model_id, prompt_version, prompt_sha256, started_at, doc_count) "
            "VALUES (?,?,?,?,?,?)",
            (RUN_ID, MODEL, "rulebook.md@" + sha[:12], sha, now, n))
con.commit()
con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
con.close()

# ---- chunk files ----------------------------------------------------------
size = (n + NCHUNK - 1) // NCHUNK
paths = []
for i in range(NCHUNK):
    part = relids[i*size:(i+1)*size]
    if not part:
        continue
    p = os.path.join(HERE, "chunk_%02d.txt" % i)
    open(p, "w").write("\n".join(str(x) for x in part) + "\n")
    paths.append((p, len(part)))

print("run_id     :", RUN_ID)
print("model      :", MODEL)
print("rulebook   :", sha[:12], "(sha256 prefix)")
print("slice      :", CUTOFF, "-> latest;", n, "releases")
print("chunks     :", len(paths))
for p, c in paths:
    print("   %-14s %d" % (os.path.basename(p), c))
