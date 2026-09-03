#!/usr/bin/env python3
"""
Identify the kept words worth dropping before sweep 2, in two groups:

  FRAGMENT  a piece of a term we already have (artificial < artificial
            intelligence). Safe to drop: the real releases enter through the
            full term. No judgement needed.
  BROAD     not a fragment, but adds a lot of new releases — shown WITH example
            titles of what it newly pulls in, so the drop call is evidence-based.

Prints only. Dropping happens in a second step once the lists are seen.
"""
import re, sqlite3, os

HERE = os.path.dirname(os.path.abspath(__file__))
con = sqlite3.connect("file:%s?mode=ro" % os.path.join(HERE, "corpus.db"), uri=True)
rev = sqlite3.connect("file:%s?mode=ro" % os.path.join(HERE, "reviews.db"), uri=True)

FTS = re.compile(r"[A-Za-z0-9]+")
STOP = {"and", "of", "the", "like", "including", "use", "role", "to", "in", "for"}


def toks(t):
    return [x for x in FTS.findall(t.lower()) if x]


def sing(w):
    return w[:-1] if len(w) > 3 and w.endswith("s") else w


win = set(r[0] for r in con.execute(
    "SELECT relid FROM releases WHERE release_date BETWEEN '2024-01-01' AND '2026-12-31'"))


def hits(term):
    q = '"' + " ".join(toks(term)) + '"'
    if not toks(term):
        return set()
    return set(r[0] for r in con.execute(
        "SELECT rowid FROM releases_fts WHERE releases_fts MATCH ?", (q,))) & win


accepted = [r[0] for r in con.execute("SELECT term FROM terms WHERE status='accepted'")]
multi = [t for t in accepted if len(toks(t)) > 1]
multi_sets = [(t, set(sing(x) for x in toks(t))) for t in multi]

keeps = [r[0] for r in rev.execute("SELECT term FROM review_decisions WHERE decision='keep'")]
rev.close()

base = set()
for t in accepted:
    base |= hits(t)


def fragment_of(term):
    ks = set(sing(x) for x in toks(term) if x not in STOP)
    if not ks:
        return None
    for name, s in multi_sets:
        if ks and ks <= s:
            return name
    return None


frags, broad = [], []
for t in keeps:
    fo = fragment_of(t)
    add = len(hits(t) - base)
    if fo:
        frags.append((t, fo, add))
    else:
        broad.append((t, add))

print("=" * 68)
print("GROUP 1 — FRAGMENTS of terms we already have  (safe drops)")
print("=" * 68)
for t, fo, add in sorted(frags, key=lambda x: -x[2]):
    print("  %-30s  piece of '%s'   (+%d new)" % (t[:30], fo, add))
print("  %d fragments" % len(frags))

print("\n" + "=" * 68)
print("GROUP 2 — BROAD words adding the most new releases  (check titles)")
print("=" * 68)
for t, add in sorted(broad, key=lambda x: -x[1])[:22]:
    if add < 8:
        continue
    new = sorted(hits(t) - base)[:3]
    titles = [con.execute("SELECT substr(title,1,60) FROM releases WHERE relid=?", (i,)).fetchone()[0]
              for i in new]
    print("\n  %-28s +%d new releases" % (t, add))
    for ti in titles:
        print("       · %s" % ti)
con.close()
