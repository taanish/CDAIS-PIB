#!/usr/bin/env python3
"""
Build a short 'reconsider' list from a first-pass review: the decisions most
worth a second look, each carrying its current decision so a second pass only
has to change the ones you want to.

Four buckets:
  A  kept, but "AI-"+word — finds no release "AI" doesn't already find
  B  dropped, but looks like a real AI term
  C  kept, but adjacent technology, not AI itself
  D  kept, but too few releases to verify from the sheet
"""
import csv, os, re, sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
RUN = "patch-v2-2024-2026"
SHEET = os.path.join(HERE, "review_candidates.csv")
OUT = os.path.join(HERE, "reconsider_candidates.csv")

RESCUE = {"robotics", "digital twin", "digital twins", "sabhasaar"}
ADJACENT = {"blockchain", "dlt", "digital public", "public infrastructure",
            "computing", "data centres", "data centers"}
UNVERIFIED = {"cspai", "rsvc", "saar", "inup", "midas", "depa"}


def tokens(t):
    return [x for x in re.split(r"[^a-z0-9]+", t.lower()) if x]


def has_ai_token(t):
    return "ai" in tokens(t) or "ml" in tokens(t)


# current decisions
rev = sqlite3.connect("file:%s?mode=ro" % os.path.join(HERE, "reviews.db"), uri=True)
dec = dict(rev.execute("SELECT term, decision FROM review_decisions"))
rev.close()

# metadata + examples
con = sqlite3.connect("file:%s?mode=ro" % os.path.join(HERE, "corpus.db"), uri=True)
meta = {t: (ch, inp, tot, sh) for t, ch, inp, tot, sh in con.execute(
    "SELECT term, channel, in_pool, total, share FROM candidate_runs WHERE run_label=?", (RUN,))}
con.close()
example = {}
for r in csv.DictReader(open(SHEET)):
    example[r["term"]] = r["example_sentence"]

low2term = {t.lower(): t for t in dec}


def kindof(ch):
    if ch == "named system": return "named"
    if ch and ch.endswith("phrase"): return "phrase"
    return "shaped"


rows = []
seen = set()


def add(term, bucket):
    if term in seen or term not in meta:
        return
    seen.add(term)
    ch, inp, tot, sh = meta[term]
    rows.append({"bucket": bucket, "cur": dec.get(term, "?"), "term": term,
                 "type": kindof(ch), "ai": inp, "tot": tot,
                 "pct": "%d%%" % round((sh or 0) * 100),
                 "ex": example.get(term, "")})


# A) kept "AI-"+word compounds (but not the GPT/bot/Drishti proper names)
for t, d in dec.items():
    if d == "keep" and kindof(meta.get(t, ("",))[0]) == "shaped" and has_ai_token(t):
        add(t, "A: kept AI-word (finds nothing new)")
# B) dropped but looks real
for low in RESCUE:
    if low in low2term:
        add(low2term[low], "B: dropped, looks like real AI")
# C) kept adjacent tech
for low in ADJACENT:
    if low in low2term and dec.get(low2term[low]) == "keep":
        add(low2term[low], "C: kept, adjacent tech not AI")
# D) kept, few releases
for low in UNVERIFIED:
    if low in low2term and dec.get(low2term[low]) == "keep":
        add(low2term[low], "D: kept, too few releases to verify")

order = {"A": 0, "B": 1, "C": 2, "D": 3}
rows.sort(key=lambda r: (order[r["bucket"][0]], -r["ai"]))

with open(OUT, "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["DECISION (keep/drop)", "group", "term", "type", "ai_releases",
                "total_releases", "pct_ai", "example_sentence", "current"])
    for r in rows:
        w.writerow([r["cur"], r["bucket"], r["term"], r["type"], r["ai"],
                    r["tot"], r["pct"], r["ex"], r["cur"]])

import collections
c = collections.Counter(r["bucket"] for r in rows)
print("wrote %s — %d items to reconsider" % (OUT, len(rows)))
for b in sorted(c, key=lambda x: order[x[0]]):
    print("  %-42s %d" % (b, c[b]))
