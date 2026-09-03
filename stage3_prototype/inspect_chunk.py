#!/usr/bin/env python3
"""Eyeball a chunk's JSONL before trusting it. Read-only."""
import json, sqlite3, sys, os

DB = "/Users/taanish/Desktop/CDAIS/PIB/corpus.db"
path = sys.argv[1]
con = sqlite3.connect(DB)

rows, bad = [], []
for i, line in enumerate(open(path), 1):
    line = line.strip()
    if not line:
        continue
    try:
        rows.append(json.loads(line))
    except Exception as e:
        bad.append((i, str(e)))

print("file:", os.path.basename(path))
print("lines parsed:", len(rows), "| parse errors:", len(bad))
for i, e in bad[:5]:
    print("   line", i, e)

def title(relid):
    r = con.execute("SELECT release_date, title FROM releases WHERE relid=?", (relid,)).fetchone()
    return r if r else ("?", "?")

# verbatim check + field presence
miss_q = 0
for r in rows:
    body = con.execute("SELECT body_text FROM releases WHERE relid=?", (r["relid"],)).fetchone()
    body = (body[0] or "") if body else ""
    for q in [r.get("type_evidence", "")] + [s.get("evidence_quote", "") for s in r.get("systems", [])]:
        if q and q not in body:
            miss_q += 1
print("quotes NOT found verbatim in body:", miss_q)

print("\n===== AI SYSTEM records =====")
for r in rows:
    if r.get("mention_type") == "AI system" or r.get("systems"):
        d, t = title(r["relid"])
        print("\n[%s] %s  (%s)" % (r["relid"], (t or "")[:70], d))
        print("   type=%s subst=%s conf=%s" % (r["mention_type"], r.get("is_substantive"), r.get("confidence")))
        for s in r.get("systems", []):
            print("   - %s | %s | %s | %s | %s" % (
                s.get("system_name"), s.get("deploying_body"),
                s.get("application_domain"), s.get("lifecycle_stage"),
                s.get("technology_type")))
            print("     ev: %s" % (s.get("evidence_quote", "")[:160]))

print("\n===== sample of 'Not AI' calls (check these are really not AI) =====")
shown = 0
for r in rows:
    if r.get("mention_type") == "Not AI":
        d, t = title(r["relid"])
        print("[%s] %s" % (r["relid"], (t or "")[:80]))
        print("    why: %s" % (r.get("type_evidence", "")[:140]))
        shown += 1
        if shown >= 8:
            break
con.close()
