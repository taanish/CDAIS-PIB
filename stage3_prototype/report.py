#!/usr/bin/env python3
"""Summaries + exports off ai_classifications for the prototype."""
import csv, json, os, sqlite3

HERE   = os.path.dirname(os.path.abspath(__file__))
DB     = "/Users/taanish/Desktop/CDAIS/PIB/corpus.db"
RUN_ID = "proto-2026-07to08-sonnet-r1"
con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row

def rows(sql, *a):
    return con.execute(sql, a).fetchall()

print("=== releases by type (distinct releases) ===")
by_type = rows("SELECT mention_type, COUNT(DISTINCT relid) c FROM ai_classifications "
               "WHERE run_id=? GROUP BY mention_type ORDER BY c DESC", RUN_ID)
for r in by_type:
    print("  %-12s %4d" % (r["mention_type"], r["c"]))

dep_rel = rows("SELECT COUNT(DISTINCT relid) c FROM ai_classifications "
               "WHERE run_id=? AND system_name IS NOT NULL", RUN_ID)[0]["c"]
sys_rec = rows("SELECT COUNT(*) c FROM ai_classifications "
               "WHERE run_id=? AND system_name IS NOT NULL", RUN_ID)[0]["c"]
print("\nreleases with >=1 system :", dep_rel)
print("system records total     :", sys_rec)

print("\n=== system records by stage ===")
for r in rows("SELECT lifecycle_stage, COUNT(*) c FROM ai_classifications "
              "WHERE run_id=? AND system_name IS NOT NULL GROUP BY lifecycle_stage ORDER BY c DESC", RUN_ID):
    print("  %-10s %3d" % (r["lifecycle_stage"], r["c"]))

print("\n=== system records by area ===")
for r in rows("SELECT application_domain, COUNT(*) c FROM ai_classifications "
              "WHERE run_id=? AND system_name IS NOT NULL GROUP BY application_domain ORDER BY c DESC", RUN_ID):
    print("  %-20s %3d" % (r["application_domain"], r["c"]))

# ---- deployment shortlist CSV ------------------------------------------
dep_sql = """
SELECT a.relid, r.release_date, r.title, f.url,
       a.system_name, a.deploying_body, a.application_domain, a.lifecycle_stage,
       a.technology_type, a.beneficiary_scale, a.budget_mentioned, a.use_case_given,
       a.mention_type, a.confidence, a.evidence_quote
FROM ai_classifications a
JOIN releases r  ON r.relid=a.relid
LEFT JOIN fetch_log f ON f.relid=a.relid
WHERE a.run_id=? AND a.system_name IS NOT NULL
ORDER BY r.release_date, a.relid, a.system_seq
"""
dep = rows(dep_sql, RUN_ID)
cols = ["relid","release_date","title","url","system_name","deploying_body",
        "application_domain","lifecycle_stage","technology_type","beneficiary_scale",
        "budget_mentioned","use_case_given","mention_type","confidence","evidence_quote"]
csv_path = os.path.join(HERE, "deployments_shortlist.csv")
with open(csv_path, "w", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(cols)
    for r in dep:
        w.writerow([r[c] for c in cols])
print("\ndeployment shortlist CSV :", csv_path, "(%d rows)" % len(dep))

# ---- full per-release CSV ----------------------------------------------
rel_sql = """
SELECT a.relid, r.release_date, r.title, f.url, a.mention_type,
       a.is_ai_relevant, a.is_substantive, a.confidence,
       (SELECT COUNT(*) FROM ai_classifications b
        WHERE b.run_id=a.run_id AND b.relid=a.relid AND b.system_name IS NOT NULL) n_systems
FROM ai_classifications a
JOIN releases r  ON r.relid=a.relid
LEFT JOIN fetch_log f ON f.relid=a.relid
WHERE a.run_id=? AND a.system_seq=0
ORDER BY r.release_date, a.relid
"""
allc = rows(rel_sql, RUN_ID)
allcols = ["relid","release_date","title","url","mention_type","is_ai_relevant",
           "is_substantive","n_systems","confidence"]
all_path = os.path.join(HERE, "all_classifications.csv")
with open(all_path, "w", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(allcols)
    for r in allc:
        w.writerow([r[c] for c in allcols])
print("full per-release CSV     :", all_path, "(%d releases)" % len(allc))

# ---- demo.json for the artifact ----------------------------------------
demo = {
    "run_id": RUN_ID,
    "slice": "2026-07-01 to 2026-08-05",
    "by_type": {r["mention_type"]: r["c"] for r in by_type},
    "deployment_releases": dep_rel,
    "system_records": sys_rec,
    "by_stage": {r["lifecycle_stage"]: r["c"] for r in rows(
        "SELECT lifecycle_stage, COUNT(*) c FROM ai_classifications "
        "WHERE run_id=? AND system_name IS NOT NULL GROUP BY lifecycle_stage", RUN_ID)},
    "by_area": {r["application_domain"]: r["c"] for r in rows(
        "SELECT application_domain, COUNT(*) c FROM ai_classifications "
        "WHERE run_id=? AND system_name IS NOT NULL GROUP BY application_domain", RUN_ID)},
    "samples": [dict(r) for r in dep],
}
with open(os.path.join(HERE, "demo.json"), "w") as fh:
    json.dump(demo, fh, indent=2, default=str)
print("demo.json written")
con.close()
