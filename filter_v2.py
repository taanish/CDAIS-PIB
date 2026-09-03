#!/usr/bin/env python3
"""
Revised candidate filter — test run on a single year.

What changed from the original filter, and why:

  DELETED  short-word-at-the-edges     killed real terms ("AI model", "ML ops")
                                       to catch scraps the filler-word rule
                                       already catches.
  DELETED  must-bring-a-new-release    punished the best vocabulary: a phrase
                                       appearing only in AI releases adds no new
                                       releases, so it was thrown out.
  DELETED  too-common (>25%)           redundant once relevance is measured by
                                       share — a word that is everywhere fails
                                       the share test on its own.
  DELETED  top-40-per-word cap         an arbitrary quantity limit, and the
                                       broken relevance test decided which 40.
  NARROWED minimum-count               was applied to all three hunts. Now: none
                                       for AI-shaped words (a system named once,
                                       like CrimeGPT, is exactly what we want),
                                       2 for named systems, 3 for phrases.
  REPLACED relevance test              was: how thickly does the phrase appear
                                       inside AI releases versus outside. That
                                       comparison is distorted because non-AI
                                       releases outnumber AI ones ~5:1, so junk
                                       like "take home ration" passed.
                                       Now: of every release containing the
                                       phrase, what share are already AI ones.
  KEPT     link strip, filler-word rule, blocklist, ministry-acronym block.
  KEPT     the known flaw: share punishes high-yield words, because a word that
                                       brings in many new releases has, by
                                       definition, many releases outside the
                                       pile. That is why a word can also pass on
                                       raw count alone ("share OR count").

No threshold is hardcoded. Every candidate's real numbers are written to the
database, so the cutoff is a query rather than a decision baked into this file.

    python3 filter_v2.py --year 2025 --label patch-v2
    python3 filter_v2.py --year 2025 --label patch-v2 --no-write-db
"""
import argparse
import collections
import os
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "corpus.db")

# ---- the hunts -------------------------------------------------------------
# AI-shaped words. Narrow on purpose: these are trusted on their form alone, so
# they carry no minimum count.
MORPH = [
    (r"\b([A-Za-z]{2,}GPT)\b",                       "*GPT"),
    (r"\b(Smart[A-Z][A-Za-z]{2,})\b",                "Smart*"),
    (r"\b([A-Za-z]{3,}[-–]AI|AI[-–][A-Za-z]{3,})\b", "AI-*"),
    (r"\b([A-Z][A-Za-z]{2,}\s?Drishti)\b",           "*Drishti"),
    (r"\b([A-Za-z]{3,}(?:bot|Bot))\b",               "*bot"),
]

SYSTEM_WORD = re.compile(
    r"^(?:platform|portal|system|systems|app|application|tool|toolkit|mission|"
    r"model|engine|dashboard|chatbot|bot|software|module|suite|framework|"
    r"initiative|scheme|programme|program|project|solution|technology)\b", re.I)
HONORIFIC = set("shri smt sh dr prof mr mrs ms hon hon'ble shrimati kumari".split())
CAPSEQ = re.compile(r"\b([A-Z][A-Za-z0-9]{2,}(?:\s+[A-Z][A-Za-z0-9]{2,}){0,3})\b")

URL_RE = re.compile(r"https?://\S+|www\.\S+", re.I)
MINISTRY_ABBR = re.compile(r"^(?:Mo|Do|Dept)[A-Z]")
# The blanket acronym ban was dropped: real AI systems are acronyms (ANPR is on
# the seed list). Only ministry short-forms are reliably organisations.

STOP = set("""the a an and or of in to for on at by with from as is are was were be been
being this that these those it its his her their our your my we you they he she
i has have had do does did will would shall should may might can could must not
no nor but if then than so such also more most other some any all both each few
own same too very s t don now d ll m o re ve y ain shri smt dr km lakh crore
government india indian ministry department minister union state states national
new delhi press information bureau said says today year years month months day days
also including various total per cent percent number one two three four five
under over during through between among about after before while since upon
shall hon ble sri via etc vide inter alia""".split())

MINISTRY_WORDS = set("""ministry department secretariat commission council authority
board bureau office cabinet committee corporation institute organisation organization""".split())

BLOCK = {"intelligence", "smart cities mission", "digital india", "make in india",
         "startup india", "atmanirbhar bharat", "viksit bharat", "narendra modi",
         "lok sabha", "rajya sabha", "prime minister"}

# Minimum length is 2 characters, enforced by TOKEN itself. That is what lets
# "AI model" and "ML ops" survive now that the 3-character edge rule is gone.
TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9'’]{1,}")
FTS_TOK = re.compile(r"[A-Za-z0-9]+")

MIN_SHAPE = 1     # AI-shaped words: one mention is enough
MIN_NAMED = 2     # named systems: twice, so a typo or a person does not qualify
MIN_PHRASE = 3    # phrases: enough examples that a share means something


def grams_of(text, maxn=3):
    """Every run of 1..maxn words, minus runs that start or end with filler."""
    low = [w.lower() for w in TOKEN.findall(text)]
    out = set()
    L = len(low)
    for n in range(1, maxn + 1):
        for j in range(L - n + 1):
            g = low[j:j + n]
            if g[0] in STOP or g[-1] in STOP:
                continue
            out.add(" ".join(g))
    return out


def fts_query(term):
    toks = FTS_TOK.findall(term.lower())
    return ('"' + " ".join(toks) + '"') if toks else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", default="2025", help="single year, or use --from/--to")
    ap.add_argument("--from", dest="yr_from")
    ap.add_argument("--to", dest="yr_to")
    ap.add_argument("--label", default="patch-v2")
    ap.add_argument("--no-write-db", dest="write_db", action="store_false", default=True)
    a = ap.parse_args()

    t0 = time.time()
    con = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
    if a.yr_from or a.yr_to:
        a.year = "%s-%s" % (a.yr_from or a.yr_to, a.yr_to or a.yr_from)
        lo, hi = (a.yr_from or a.yr_to) + "-01-01", (a.yr_to or a.yr_from) + "-12-31"
    else:
        lo, hi = a.year + "-01-01", a.year + "-12-31"

    docs = {}
    for relid, title, body in con.execute(
            "SELECT relid, COALESCE(title,''), COALESCE(body_text,'') FROM releases "
            "WHERE release_date>=? AND release_date<=?", (lo, hi)):
        docs[relid] = URL_RE.sub(" ", title + " \n " + body)
    year_ids = set(docs)
    print("year %s: %d releases" % (a.year, len(year_ids)))

    accepted = [r[0] for r in con.execute(
        "SELECT term FROM terms WHERE status='accepted' ORDER BY term")]
    # words already ruled on in an earlier sweep — accepted OR rejected — must
    # not be surfaced again as candidates, or a second sweep re-asks you about
    # everything you already dropped.
    decided = set(r[0].lower() for r in con.execute(
        "SELECT term FROM terms WHERE status IN ('accepted','rejected')"))
    pool = set()
    per_term = {}
    for t in accepted:
        q = fts_query(t)
        ids = set()
        if q:
            ids = set(r[0] for r in con.execute(
                "SELECT rowid FROM releases_fts WHERE releases_fts MATCH ?", (q,))) & year_ids
        per_term[t] = ids
        pool |= ids
    print("accepted words: %d  ->  AI pile: %d releases (%.1f%%)"
          % (len(accepted), len(pool), 100.0 * len(pool) / max(1, len(year_ids))))

    # ---- hunt, inside the AI pile only ------------------------------------
    morph_rx = [(re.compile(p), lab) for p, lab in MORPH]
    acc_rx = [re.compile(r"\b" + re.escape(t).replace(r"\ ", r"\s+") + r"\b", re.I)
              for t in sorted(accepted, key=lambda t: -len(per_term[t]))[:30]]

    # Counts are RELEASE counts, not mention counts: a candidate seen five times
    # in one release still counts as one release. Each release therefore builds
    # its own `seen` set first, and the global counter is bumped once per key.
    # The hunts run shape -> named -> phrase, and the first to claim a key inside
    # a release wins, so "ChatGPT" is recorded as an AI-shaped word rather than
    # as a one-word phrase.
    counts = collections.Counter()
    surface, kind = {}, {}
    for i in pool:
        d = docs[i]
        seen = {}
        for rx, lab in morph_rx:
            for m in rx.findall(d):
                w = (m if isinstance(m, str) else m[0]).strip()
                if len(w) < 3:
                    continue
                k = w.lower()
                seen.setdefault(k, lab)
                surface.setdefault(k, w)
        for rx in acc_rx:
            for m in rx.finditer(d):
                seg = d[max(0, m.start() - 120):m.end() + 120]
                for name in CAPSEQ.findall(seg):
                    nm = re.sub(r"\s+", " ", name).strip()
                    toks = nm.lower().split()
                    if not toks or toks[0] in HONORIFIC or toks[0] in STOP or toks[-1] in STOP:
                        continue
                    if any(t in MINISTRY_WORDS for t in toks) or MINISTRY_ABBR.match(nm):
                        continue
                    pos = seg.find(nm)
                    if not SYSTEM_WORD.match(seg[pos + len(nm):].lstrip(" ,.'’()")):
                        continue
                    k = nm.lower()
                    seen.setdefault(k, "named system")
                    surface.setdefault(k, nm)
        for g in grams_of(d):
            seen.setdefault(g, "%d-word phrase" % (g.count(" ") + 1))
            surface.setdefault(g, g)
        for k, ch in seen.items():
            counts[k] += 1
            kind.setdefault(k, ch)

    known = decided
    blocked = []
    survivors = set()
    for k, n in counts.items():
        if k in known:
            continue
        if k in BLOCK:
            blocked.append((surface[k], kind[k], n, "known troublemaker"))
            continue
        ch = kind[k]
        if ch.endswith("phrase"):
            floor = MIN_PHRASE
        elif ch == "named system":
            floor = MIN_NAMED
        else:
            floor = MIN_SHAPE          # AI-shaped word: one release is enough
        if n >= floor:
            survivors.add(k)
    print("hunted %d distinct candidates -> %d clear the minimum count"
          % (len(counts), len(survivors)))
    print("blocked by the troublemaker list: %d  (%s)"
          % (len(blocked), ", ".join(b[0] for b in blocked[:8]) or "none"))

    # ---- how often does each survivor appear across the WHOLE year? -------
    # This is the denominator of the share. One sweep of every release in the
    # year, not one lookup per candidate.
    total = collections.Counter()
    in_pool = collections.Counter()
    phrase_survivors = set(k for k in survivors if kind[k].endswith("phrase"))
    for i, d in docs.items():
        gs = grams_of(d) & phrase_survivors
        for g in gs:
            total[g] += 1
            if i in pool:
                in_pool[g] += 1
    # shape/named candidates are not word-runs, so count them by regex
    for k in survivors - phrase_survivors:
        rx = re.compile(r"\b" + re.escape(surface[k]).replace(r"\ ", r"\s+") + r"\b", re.I)
        for i, d in docs.items():
            if rx.search(d):
                total[k] += 1
                if i in pool:
                    in_pool[k] += 1

    # A phrase that CONTAINS a word we already accepted can never find a release
    # we do not already have — every release matching "ai driven" already matches
    # "AI". Flagged rather than deleted, because such a phrase is still real
    # vocabulary if the word list itself is a deliverable.
    acc_lower = [t.lower().split() for t in accepted]

    def redundant(phrase):
        w = phrase.split()
        for tw in acc_lower:
            n = len(tw)
            for j in range(len(w) - n + 1):
                if w[j:j + n] == tw:
                    return True
        return False

    rows = []
    for k in survivors:
        tot = total.get(k, 0)
        inp = in_pool.get(k, 0)
        if tot == 0:
            continue
        rows.append({"term": surface[k], "channel": kind[k], "in_pool": inp,
                     "total": tot, "share": inp / float(tot),
                     "redundant": 1 if redundant(k) else 0})
    print("candidates with numbers: %d" % len(rows))

    # ---- what would different cutoffs give you? ---------------------------
    phrases = [r for r in rows if r["channel"].endswith("phrase")]
    shapes = [r for r in rows if not r["channel"].endswith("phrase")]
    fresh = [r for r in phrases if not r["redundant"]]
    print("\nAI-shaped words + named systems (no cutoff applied): %d" % len(shapes))
    print("phrases: %d, of which %d contain a word we already have"
          % (len(phrases), len(phrases) - len(fresh)))

    def grid(items, title):
        print("\n%s" % title)
        print("  %-10s %9s %9s %9s %9s %9s"
              % ("share>=", ">=5 rel", ">=10", ">=20", ">=40", ">=80"))
        for s in (0.50, 0.60, 0.70, 0.80, 0.90):
            cells = [sum(1 for r in items if r["share"] >= s and r["total"] >= c)
                     for c in (5, 10, 20, 40, 80)]
            print("  %-10.0f%% %9d %9d %9d %9d %9d" % tuple([s * 100] + cells))

    grid(phrases, "ALL phrases, needing BOTH a share and enough releases:")
    grid(fresh, "ONLY phrases that could find new releases (redundant ones removed):")

    # Close the reader BEFORE writing. Adding a column needs an exclusive lock,
    # and this process's own open read connection is enough to deny it.
    con.close()
    if a.write_db:
        write(rows, blocked, a.label, a.year, len(pool), len(year_ids))
    print("\ndone in %.0fs" % (time.time() - t0))


def write(rows, blocked, label, year, pool_n, year_n):
    rw = sqlite3.connect(DB, timeout=60)
    rw.execute("""CREATE TABLE IF NOT EXISTS candidate_runs (
                    run_label TEXT, term TEXT, channel TEXT, year TEXT,
                    in_pool INTEGER, total INTEGER, share REAL,
                    status TEXT, note TEXT, created_at TEXT,
                    PRIMARY KEY (run_label, term))""")
    if "redundant" not in set(r[1] for r in rw.execute("PRAGMA table_info(candidate_runs)")):
        rw.execute("ALTER TABLE candidate_runs ADD COLUMN redundant INTEGER DEFAULT 0")
    rw.execute("""CREATE TABLE IF NOT EXISTS candidate_run_meta (
                    run_label TEXT PRIMARY KEY, year TEXT, pool_releases INTEGER,
                    year_releases INTEGER, candidates INTEGER, blocked INTEGER,
                    created_at TEXT, note TEXT)""")
    rw.execute("DELETE FROM candidate_runs WHERE run_label=?", (label,))
    now = datetime.now(timezone.utc).isoformat()
    rw.executemany("INSERT OR REPLACE INTO candidate_runs VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                   [(label, r["term"], r["channel"], year, r["in_pool"], r["total"],
                     round(r["share"], 4), "candidate", None, now, r["redundant"])
                    for r in rows])
    rw.executemany("INSERT OR REPLACE INTO candidate_runs VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                   [(label, b[0], b[1], year, b[2], None, None, "blocked", b[3], now, 0)
                    for b in blocked])
    rw.execute("INSERT OR REPLACE INTO candidate_run_meta VALUES (?,?,?,?,?,?,?,?)",
               (label, year, pool_n, year_n, len(rows), len(blocked), now,
                "share-or-count filter; thresholds applied at query time"))
    rw.commit()
    rw.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    rw.close()
    print("\nwritten to corpus.db as run_label='%s'" % label)
    print("  table candidate_runs      (%d candidates + %d blocked)" % (len(rows), len(blocked)))
    print("  table candidate_run_meta  (what this run was)")


if __name__ == "__main__":
    main()
