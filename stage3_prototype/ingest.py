#!/usr/bin/env python3
"""
Load the subagent JSONL chunks into ai_classifications.

- One row per system for AI-system releases (system_seq 0..N-1).
- One row (system_seq 0, system fields NULL) for everything else.
- evidence_start/end are computed here by finding the verbatim quote in the
  full body_text, so offsets are exact (the model never has to count chars).
Tolerant of malformed lines: it reports them rather than crashing.
"""
import glob, json, os, sqlite3

HERE   = os.path.dirname(os.path.abspath(__file__))
DB     = "/Users/taanish/Desktop/CDAIS/PIB/corpus.db"
RUN_ID = "proto-2026-07to08-sonnet-r1"

con = sqlite3.connect(DB, timeout=60)
con.execute("DELETE FROM ai_classifications WHERE run_id=?", (RUN_ID,))

bodies = {}
def body(relid):
    if relid not in bodies:
        r = con.execute("SELECT body_text FROM releases WHERE relid=?", (relid,)).fetchone()
        bodies[relid] = (r[0] or "") if r else ""
    return bodies[relid]

def offs(relid, quote):
    if not quote:
        return (None, None)
    b = body(relid)
    i = b.find(quote)
    return (i, i + len(quote)) if i >= 0 else (None, None)

def norm_stage(s):
    if not s:
        return None
    s = s.strip().lower()
    return s if s in ("announced", "buying", "trial", "working") else s

seen, bad, nrows, nsys = set(), [], 0, 0
for path in sorted(glob.glob(os.path.join(HERE, "out_*.jsonl"))):
    for ln, line in enumerate(open(path), 1):
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
            relid = int(r["relid"])
        except Exception as e:
            bad.append((os.path.basename(path), ln, str(e)))
            continue
        seen.add(relid)
        rel = dict(
            relid=relid, run_id=RUN_ID,
            is_ai_relevant=int(r.get("is_ai_relevant", 1)),
            is_substantive=int(r.get("is_substantive", 1)),
            mention_type=r.get("mention_type"),
            type_evidence=r.get("type_evidence"),
            confidence=r.get("confidence"),
        )
        systems = r.get("systems") or []
        if not systems:
            s, e = offs(relid, rel["type_evidence"])
            con.execute("""INSERT OR REPLACE INTO ai_classifications
                (relid,run_id,system_seq,is_ai_relevant,is_substantive,mention_type,
                 type_evidence,lifecycle_stage,deploying_body,system_name,application_domain,
                 technology_type,beneficiary_scale,budget_mentioned,use_case_given,
                 evidence_quote,evidence_start,evidence_end,confidence)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (relid, RUN_ID, 0, rel["is_ai_relevant"], rel["is_substantive"],
                 rel["mention_type"], rel["type_evidence"], None, None, None, None,
                 None, None, None, None, rel["type_evidence"], s, e, rel["confidence"]))
            nrows += 1
        else:
            for seq, sy in enumerate(systems):
                q = sy.get("evidence_quote")
                s, e = offs(relid, q)
                con.execute("""INSERT OR REPLACE INTO ai_classifications
                    (relid,run_id,system_seq,is_ai_relevant,is_substantive,mention_type,
                     type_evidence,lifecycle_stage,deploying_body,system_name,application_domain,
                     technology_type,beneficiary_scale,budget_mentioned,use_case_given,
                     evidence_quote,evidence_start,evidence_end,confidence)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (relid, RUN_ID, seq, rel["is_ai_relevant"], rel["is_substantive"],
                     rel["mention_type"], rel["type_evidence"], norm_stage(sy.get("lifecycle_stage")),
                     sy.get("deploying_body"), sy.get("system_name"), sy.get("application_domain"),
                     sy.get("technology_type"), sy.get("beneficiary_scale"), sy.get("budget_mentioned"),
                     (int(sy["use_case_given"]) if sy.get("use_case_given") is not None else None),
                     q, s, e, rel["confidence"]))
                nrows += 1
                nsys += 1

con.execute("UPDATE classification_runs SET finished_at=datetime('now'), doc_count=? "
            "WHERE run_id=?", (len(seen), RUN_ID))
con.commit()
con.execute("PRAGMA wal_checkpoint(TRUNCATE)")

# ---- coverage check against the intended slice --------------------------
want = set()
for f in glob.glob(os.path.join(HERE, "chunk_*.txt")):
    for x in open(f):
        x = x.strip()
        if x:
            want.add(int(x))
missing = sorted(want - seen)
extra   = sorted(seen - want)

print("rows written        :", nrows, "(%d system rows)" % nsys)
print("releases classified :", len(seen), "of", len(want), "intended")
print("malformed lines     :", len(bad))
for b in bad[:10]:
    print("   ", b)
print("missing releases    :", len(missing), missing[:20])
print("unexpected releases :", len(extra), extra[:20])
con.close()
