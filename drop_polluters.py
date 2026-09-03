#!/usr/bin/env python3
"""Drop the identified polluter words, then re-measure clean growth."""
import re, sqlite3, os
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))

# fragments of terms we already have — safe by the "the real releases enter
# through the full term" logic
FRAGMENTS = ["artificial", "machine", "use of artificial", "facial",
             "Large Language", "like artificial", "language models",
             "large language models", "role of artificial"]
# broad words whose new releases were checked and are not about AI
BROAD = ["emerging technologies", "UMANG", "atal tinkering",
         "communication technology", "diksha", "data centres", "data centers",
         "trustworthy", "metering", "frontier technologies", "Blockchain",
         "dataset", "meri panchayat app", "WAVES OTT", "technology leaders",
         "maitris", "deep tech startups", "algorithms"]
DROP = FRAGMENTS + BROAD

rw = sqlite3.connect(os.path.join(HERE, "reviews.db"), timeout=60)
now = datetime.now(timezone.utc).isoformat()
n = 0
for t in DROP:
    cur = rw.execute("UPDATE review_decisions SET decision='drop', decided_at=? "
                     "WHERE term=? AND decision='keep'", (now, t))
    n += cur.rowcount
rw.commit()
rw.close()
print("dropped %d of %d requested (%d were already not 'keep')" % (n, len(DROP), len(DROP) - n))

# ---- re-measure ----
con = sqlite3.connect("file:%s?mode=ro" % os.path.join(HERE, "corpus.db"), uri=True)
rev = sqlite3.connect("file:%s?mode=ro" % os.path.join(HERE, "reviews.db"), uri=True)
FTS = re.compile(r"[A-Za-z0-9]+")


def hits(term):
    q = '"' + " ".join(FTS.findall(term.lower())) + '"'
    win = WIN
    return set(r[0] for r in con.execute(
        "SELECT rowid FROM releases_fts WHERE releases_fts MATCH ?", (q,))) & win


WIN = set(r[0] for r in con.execute(
    "SELECT relid FROM releases WHERE release_date BETWEEN '2024-01-01' AND '2026-12-31'"))
orig = [r[0] for r in con.execute("SELECT term FROM terms WHERE status='accepted'")]
keeps = [r[0] for r in rev.execute("SELECT term FROM review_decisions WHERE decision='keep'")]
rev.close()

base = set()
for t in orig:
    base |= hits(t)
clean = set(base)
per = {}
for t in keeps:
    h = hits(t)
    per[t] = len(h - base)
    clean |= h
added = clean - base
print()
print("baseline (34 seeds)          : %d releases" % len(base))
print("after CLEANED sweep 1        : %d releases  (kept words now: %d)" % (len(clean), len(keeps)))
print("clean new releases added     : %d   (was 1388 before cleanup)" % len(added))
print()
print("top kept words still adding new releases:")
for t in sorted(keeps, key=lambda x: -per[x])[:15]:
    if per[t] > 0:
        print("   %-30s +%d" % (t[:30], per[t]))
con.close()
