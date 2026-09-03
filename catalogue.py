#!/usr/bin/env python3
"""
Attribution-preserving iterative keyword expansion  (workplan step 1.2).

expand.py answered "what terms should we add?". It could not answer "because of
which seed?" — it pooled every matched document together before mining, so the
link between a seed and the vocabulary it surfaced was destroyed. This script
keeps that link, because the audit trail is the deliverable:

    seed term  ->  releases it matches
               ->  extended terms mined from THOSE releases (parent recorded)
               ->  releases the extended terms add that the seed missed
               ->  further extended terms, until a round adds nothing

    python3 catalogue.py run                 # full loop, writes catalogue_2024_2026/
    python3 catalogue.py run --max-rounds 2
    python3 catalogue.py run --no-write-db   # artifacts only, leave corpus.db alone

Matching goes through the FTS5 index (whole-word, same semantics as PIB's own
search) so a term costs milliseconds, not a corpus sweep. Mining is regex over
the matched subset only — a few thousand documents, never the whole corpus.
"""
import argparse
import collections
import csv
import os
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "corpus.db")
OUTDIR = os.path.join(HERE, "catalogue_2024_2026")

WINDOW_LO = "2024-01-01"
WINDOW_HI = "2026-12-31"

# ------------------------------------------------------------------ K1 seeds --
# The user's list, verbatim and in order. Multi-word entries are matched as
# phrases; everything is whole-word, case-insensitive.
#
# GPT is kept even though it is a known false friend in this corpus ("General
# Purpose Technologies"). It stays because the user specified it and because
# leaving it in makes the false-friend visible in the yield table rather than
# silently absent. The real GPT-family systems (ChatGPT, MausamGPT, BharatGPT)
# are single tokens and are unreachable by whole-word "GPT" — they are caught by
# the *GPT morphology pattern instead.
K1 = [
    "AI",
    "ML",
    "artificial intelligence",
    "intelligent",
    "smart",
    "automated",
    "algorithm",
    "chatbot",
    "facial recognition",
    "FRT",
    "ANPR",
    "predictive",
    "analytics",
    "GPT",
    # "known patterns" from item 15 of the seed list
    "SafeCity",
    "Safe City",
    "Smartcity",
    "Smart City",
]
# Item 15 also names Hindi equivalents. The corpus is English-only: PIB's Hindi
# archive sits behind a separate endpoint that never returned usable content.
# Recorded here so the gap is explicit rather than assumed away.
HINDI_NOTE = ("Hindi seed terms could not be run: the corpus holds English "
              "releases only (PIB's Hindi archive was unreachable during the crawl).")

# ------------------------------------------------------- discovery channels --
# Morphological shapes that signal AI but that a whole-word search cannot
# express. Pruned after measurement on 2025: e-/i-*, *Setu/Mitra and *Vision
# produced 74 of 76 candidates and were nearly all noise (they track Indian
# government digital-programme naming, not AI).
#
# camelCase was dropped: in this corpus it matched ministry acronyms (MoSPI,
# MoHUA), social handles (AmitShah) and — worst — URL path fragments that PIB
# embeds verbatim in body text ("PressReleasePage", "WriteReadData"). It added
# thousands of non-AI releases and drowned the real signal. The genuinely
# AI-shaped morphologies below stay; they are narrow enough to be liberal
# without being noise.
MORPH = [
    (r"\b([A-Za-z]{2,}GPT)\b",                       "*GPT"),
    (r"\b(Smart[A-Z][A-Za-z]{2,})\b",                "Smart*"),
    (r"\b([A-Za-z]{3,}[-–]AI|AI[-–][A-Za-z]{3,})\b", "AI-*"),
    (r"\b([A-Z][A-Za-z]{2,}\s?Drishti)\b",           "*Drishti"),
    (r"\b([A-Za-z]{3,}(?:bot|Bot))\b",               "*bot"),
]

# URLs are stripped before mining: PIB pastes full "Detailed Release:
# https://pib.gov.in/PressReleasePage.aspx?PRID=..." links into the body, and
# their path segments look like camelCase tokens to any miner.
URL_RE = re.compile(r"https?://\S+|www\.\S+", re.I)
ACRONYM_RE = re.compile(r"^[A-Z]{2,6}s?$")          # MIS, CPP, ANPR-as-candidate
MINISTRY_ABBR = re.compile(r"^(?:Mo|Do|Dept)[A-Z]")  # MoSPI, DoNER, DoTIndia

# Proximity channel: a capitalised name sitting near an accepted term AND
# described as a system. The descriptor separates "Divya Drishti tool" from
# "Shri Jitendra Singh" — person names are never followed by "platform".
SYSTEM_WORD = re.compile(
    r"^(?:platform|portal|system|systems|app|application|tool|toolkit|mission|"
    r"model|engine|dashboard|chatbot|bot|software|module|suite|framework|"
    r"initiative|scheme|programme|program|project|solution|technology)\b", re.I)
HONORIFIC = set("shri smt sh dr prof mr mrs ms hon hon'ble shrimati kumari".split())
CAPSEQ = re.compile(r"\b([A-Z][A-Za-z0-9]{2,}(?:\s+[A-Z][A-Za-z0-9]{2,}){0,3})\b")

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

# Terms that are pure drift and must never be auto-accepted, however well they
# score. "intelligence" is the classic trap in this corpus: it scores highly
# because it sits inside "artificial intelligence", then drags in the entire
# Intelligence Bureau / intelligence-agency literature.
DRIFT_BLOCK = set("""intelligence intelligence bureau smart cities mission
digital india make in india startup india atmanirbhar bharat viksit bharat
prime minister narendra modi lok sabha rajya sabha crore rupees""".split("\n"))
DRIFT_BLOCK = set(x.strip().lower() for x in DRIFT_BLOCK if x.strip())
DRIFT_BLOCK |= {"intelligence", "smart cities mission", "digital india"}

TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9'’]{1,}")
FTS_TOK = re.compile(r"[A-Za-z0-9]+")

MIN_IN = 3          # candidate must appear in >= this many of a parent's docs
MIN_LIFT = 3.0      # gates the phrase channel only; patterns bypass it
TOP_PHRASES = 40    # per parent, per round — patterns are uncapped (liberal)


# --------------------------------------------------------------- db helpers --
def connect_ro():
    if not os.path.exists(DB):
        sys.exit("no corpus at %s" % DB)
    return sqlite3.connect("file:%s?mode=ro" % DB, uri=True)


def fts_query(term):
    """Term -> an FTS5 MATCH expression, or None if unindexable.

    unicode61 splits on punctuation, so "AI-driven" is stored as two tokens and
    must be searched as the phrase "ai driven". That is deliberate: it means the
    hyphenated and spaced spellings are caught by one query.
    """
    toks = FTS_TOK.findall(term.lower())
    toks = [t for t in toks if t]
    if not toks:
        return None
    return '"' + " ".join(toks) + '"'


class Matcher(object):
    """Whole-word term -> set of relids inside the window, via FTS5."""

    def __init__(self, con, window_ids):
        self.con = con
        self.window = window_ids
        self.cache = {}

    def match(self, term):
        key = term.lower()
        if key in self.cache:
            return self.cache[key]
        q = fts_query(term)
        ids = set()
        if q:
            try:
                rows = self.con.execute(
                    "SELECT rowid FROM releases_fts WHERE releases_fts MATCH ?", (q,))
                ids = set(r[0] for r in rows) & self.window
            except sqlite3.OperationalError:
                ids = set()
        self.cache[key] = ids
        return ids


# ------------------------------------------------------------------ mining --
def grams_of(text, maxn=3):
    words = TOKEN.findall(text)
    low = [w.lower() for w in words]
    out = set()
    L = len(low)
    for n in range(1, maxn + 1):
        for j in range(L - n + 1):
            g = low[j:j + n]
            if g[0] in STOP or g[-1] in STOP:
                continue
            if len(g[0]) < 3 or len(g[-1]) < 3:
                continue
            out.add(" ".join(g))
    return out


def harvest(docs_map, doc_ids, accepted_terms):
    """Build candidate -> set(relid) over a document set, once.

    Computing this over the UNION of a round's parents and then intersecting
    per parent is exactly equivalent to mining each parent separately, and
    costs one pass instead of one pass per parent.
    """
    postings = collections.defaultdict(set)
    surface = {}
    kind = {}

    morph_rx = [(re.compile(p), lab) for p, lab in MORPH]
    acc_rx = [re.compile(r"\b" + re.escape(t).replace(r"\ ", r"\s+") + r"\b", re.I)
              for t in accepted_terms]

    for i in doc_ids:
        d = docs_map.get(i, "")
        if not d:
            continue

        # channel 1: morphology
        for rx, lab in morph_rx:
            for m in rx.findall(d):
                w = (m if isinstance(m, str) else m[0]).strip()
                if len(w) < 3:
                    continue
                k = w.lower()
                postings[k].add(i)
                surface.setdefault(k, w)
                kind.setdefault(k, lab)

        # channel 2: named systems sitting next to an accepted term
        for rx in acc_rx:
            for m in rx.finditer(d):
                seg = d[max(0, m.start() - 120):m.end() + 120]
                for name in CAPSEQ.findall(seg):
                    nm = re.sub(r"\s+", " ", name).strip()
                    toks = nm.lower().split()
                    if not toks or toks[0] in HONORIFIC or toks[0] in STOP or toks[-1] in STOP:
                        continue
                    if any(t in MINISTRY_WORDS for t in toks):
                        continue
                    # A bare acronym or a ministry abbreviation is never an AI
                    # system name in this corpus; it is an organisation. These
                    # need a human to accept them, so they don't auto-expand.
                    if ACRONYM_RE.match(nm) or MINISTRY_ABBR.match(nm):
                        continue
                    pos = seg.find(nm)
                    after = seg[pos + len(nm):].lstrip(" ,.'’()")
                    if not SYSTEM_WORD.match(after):
                        continue
                    k = nm.lower()
                    postings[k].add(i)
                    surface.setdefault(k, nm)
                    kind.setdefault(k, "near-AI name")

        # channel 3: ordinary phrases
        for g in grams_of(d):
            postings[g].add(i)
            surface.setdefault(g, g)
            kind.setdefault(g, "%d-gram" % (g.count(" ") + 1))

    return postings, surface, kind


def score(cands, parent_ids, matched_all, window_n, matcher, surface):
    """Rank one parent's candidates. Returns rows with corpus reach attached."""
    out = []
    out_n = max(1, window_n - len(matched_all))
    for k, in_ids in cands:
        term = surface[k]
        corpus_ids = matcher.match(term)
        new_ids = corpus_ids - matched_all
        if not new_ids:
            continue                                    # adds no documents
        if len(corpus_ids) > 0.25 * window_n:
            continue                                    # boilerplate, not signal
        p_in = len(in_ids) / float(max(1, len(parent_ids)))
        p_out = max(1, len(new_ids)) / float(out_n)
        out.append({"key": k, "term": term, "in_parent": len(in_ids),
                    "corpus": len(corpus_ids), "new": len(new_ids),
                    "lift": p_in / p_out if p_out else 0.0})
    return out


# -------------------------------------------------------------------- main --
def run(args):
    t0 = time.time()
    con = connect_ro()

    rows = con.execute(
        "SELECT relid, COALESCE(title,''), COALESCE(body_text,''), "
        "       COALESCE(release_date,''), COALESCE(ministry_raw,'') "
        "FROM releases WHERE release_date>=? AND release_date<=?",
        (WINDOW_LO, WINDOW_HI)).fetchall()
    docs_map = {}
    meta = {}
    for relid, title, body, date, ministry in rows:
        docs_map[relid] = URL_RE.sub(" ", title + " \n " + body)
        meta[relid] = (date, ministry, title)
    window = set(docs_map)
    window_n = len(window)
    print("window %s..%s : %d releases" % (WINDOW_LO, WINDOW_HI, window_n))

    matcher = Matcher(con, window)

    # ---- round 0: the accepted vocabulary ---------------------------------
    # The seed set is K1 (the user's list) UNION anything a human has already
    # accepted in an earlier pass — dropping "machine learning" or "Bhashini"
    # just because they aren't in K1 would silently shrink the catalogue. Their
    # recorded round/origin is preserved; K1 members are seeds at round 0.
    terms = {}        # term -> dict(round, kind, parents{}, primary_parent, ids)
    order = []
    k1_lower = set(s.lower() for s in K1)
    for s in K1:
        terms[s] = {"round": 0, "kind": "seed", "parents": {},
                    "primary": "", "ids": matcher.match(s), "origin": "seed"}
        order.append(s)
    existing = con.execute(
        "SELECT term, round, COALESCE(parent_term,''), COALESCE(reviewed_by,'human') "
        "FROM terms WHERE status='accepted'").fetchall()
    for term, rnd_db, parent, who in existing:
        if term.lower() in k1_lower or term in terms:
            continue
        terms[term] = {"round": rnd_db if rnd_db and rnd_db > 0 else 1,
                       "kind": who, "parents": {}, "primary": parent,
                       "ids": matcher.match(term), "origin": who}
        order.append(term)

    seed_terms = list(order)           # the whole accepted vocabulary
    matched_all = set()
    for t in seed_terms:
        matched_all |= terms[t]["ids"]
    print("round 0: %d accepted terms (%d K1 + %d prior) -> %d releases (%.1f%% of window)"
          % (len(seed_terms), len(K1), len(seed_terms) - len(K1), len(matched_all),
             100.0 * len(matched_all) / window_n))

    # first-discovery attribution: which term brought each release in, and when.
    # K1 order first (the user's priority), then the rest of the vocabulary.
    discovered_by = {}
    for t in seed_terms:
        for i in terms[t]["ids"]:
            discovered_by.setdefault(i, (t, terms[t]["round"]))

    rounds = [{"round": 0, "terms_added": len(seed_terms),
               "new_releases": len(matched_all), "total_releases": len(matched_all)}]

    # ---- rounds 1..N -------------------------------------------------------
    prev_round_terms = list(seed_terms)
    for rnd in range(1, args.max_rounds + 1):
        parent_union = set()
        for t in prev_round_terms:
            parent_union |= terms[t]["ids"]
        if not parent_union:
            print("round %d: no parent documents, stopping" % rnd)
            break

        # Proximity anchors are this round's parents only, capped: every anchor
        # costs a regex sweep of every parent document, and by round 3 the term
        # list is long enough that an uncapped anchor set dominates runtime.
        anchors = sorted(prev_round_terms, key=lambda t: -len(terms[t]["ids"]))[:30]
        print("round %d: mining %d parent term(s) over %d releases..."
              % (rnd, len(prev_round_terms), len(parent_union)))
        postings, surface, kind = harvest(docs_map, parent_union, anchors)

        known = set(t.lower() for t in terms)
        added = []
        for parent in prev_round_terms:
            pids = terms[parent]["ids"]
            if not pids:
                continue
            cands = []
            for k, ids in postings.items():
                if k in known or k in DRIFT_BLOCK:
                    continue
                hit = ids & pids
                if len(hit) >= MIN_IN:
                    cands.append((k, hit))
            if not cands:
                continue
            scored = score(cands, pids, matched_all, window_n, matcher, surface)

            pats = [r for r in scored if not kind[r["key"]].endswith("gram")]
            phrs = [r for r in scored if kind[r["key"]].endswith("gram")
                    and r["lift"] >= MIN_LIFT]
            pats.sort(key=lambda r: (-r["lift"], -r["new"]))
            phrs.sort(key=lambda r: (-r["lift"], -r["new"]))
            take = pats + phrs[:TOP_PHRASES]

            for r in take:
                term = r["term"]
                share = r["in_parent"] / float(max(1, len(pids)))
                if term not in terms:
                    terms[term] = {"round": rnd, "kind": kind[r["key"]],
                                   "parents": {}, "primary": parent,
                                   "ids": matcher.match(term),
                                   "best_share": share}
                    added.append(term)
                    order.append(term)
                elif terms[term]["round"] == rnd and share > terms[term].get("best_share", 0):
                    terms[term]["primary"] = parent      # strongest parent wins
                    terms[term]["best_share"] = share
                terms[term]["parents"][parent] = r["in_parent"]

        if not added:
            print("round %d: no new terms — converged" % rnd)
            break

        before = len(matched_all)
        for t in added:
            for i in terms[t]["ids"]:
                discovered_by.setdefault(i, (t, rnd))
            matched_all |= terms[t]["ids"]
        gained = len(matched_all) - before
        print("round %d: +%d terms, +%d releases (total %d, %.1f%% of window)"
              % (rnd, len(added), gained, len(matched_all),
                 100.0 * len(matched_all) / window_n))
        rounds.append({"round": rnd, "terms_added": len(added),
                       "new_releases": gained, "total_releases": len(matched_all)})

        prev_round_terms = added
        if gained == 0:
            print("round %d added terms but no documents — stopping" % rnd)
            break

    # ---- artifacts ---------------------------------------------------------
    if not os.path.isdir(OUTDIR):
        os.makedirs(OUTDIR)
    write_artifacts(OUTDIR, terms, order, matched_all, discovered_by, rounds,
                    meta, docs_map, window_n)

    if args.write_db:
        persist(terms, order, matched_all, docs_map, discovered_by)

    print("\ndone in %.0fs -> %s" % (time.time() - t0, OUTDIR))
    con.close()


def excerpt(docs_map, relid, term, width=60):
    d = docs_map.get(relid, "")
    rx = re.compile(r"\b" + re.escape(term).replace(r"\ ", r"\s+") + r"\b", re.I)
    m = rx.search(d)
    if not m:
        return ""
    s = d[max(0, m.start() - width):m.end() + width]
    return re.sub(r"\s+", " ", s).strip()


def write_artifacts(out, terms, order, matched_all, discovered_by, rounds,
                    meta, docs_map, window_n):
    URL = "https://archive.pib.gov.in/archive2/PrintRelease.aspx?relid=%d"

    # 01 — the seed list and what each seed alone is worth
    seed_ids = {}
    for s in K1:
        seed_ids[s] = terms[s]["ids"]
    with open(os.path.join(out, "01_seed_terms.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["n", "seed_term", "releases_matched", "unique_to_this_seed",
                    "pct_of_window"])
        for n, s in enumerate(K1, 1):
            others = set()
            for o in K1:
                if o != s:
                    others |= seed_ids[o]
            w.writerow([n, s, len(seed_ids[s]), len(seed_ids[s] - others),
                        "%.2f" % (100.0 * len(seed_ids[s]) / window_n)])

    # 02 — every term with its provenance
    with open(os.path.join(out, "02_terms_all.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["term", "round", "channel", "primary_parent", "all_parents",
                    "releases_matched", "releases_added_when_introduced",
                    "example_context"])
        running = set()
        for rnd in range(0, max(t["round"] for t in terms.values()) + 1):
            for t in order:
                d = terms[t]
                if d["round"] != rnd:
                    continue
                new = d["ids"] - running
                ex = ""
                if new:
                    ex = excerpt(docs_map, sorted(new)[0], t)[:160]
                w.writerow([t, rnd, d["kind"], d.get("primary", ""),
                            " | ".join("%s(%d)" % (p, c)
                                       for p, c in sorted(d["parents"].items(),
                                                          key=lambda x: -x[1])),
                            len(d["ids"]), len(new), ex])
            for t in order:
                if terms[t]["round"] == rnd:
                    running |= terms[t]["ids"]

    # 03 — one row per (release, term) match: the tagging the workplan asks for
    with open(os.path.join(out, "03_release_term_matches.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["relid", "release_date", "ministry", "title", "matched_term",
                    "term_round", "term_channel", "term_primary_parent"])
        for t in order:
            d = terms[t]
            for i in sorted(d["ids"]):
                date, ministry, title = meta[i]
                w.writerow([i, date, ministry, title, t, d["round"], d["kind"],
                            d.get("primary", "")])

    # 04 — one row per release in the pool
    with open(os.path.join(out, "04_releases.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["relid", "release_date", "ministry", "title",
                    "discovered_by_term", "discovered_in_round", "n_terms",
                    "all_matched_terms", "url"])
        per_rel = collections.defaultdict(list)
        for t in order:
            for i in terms[t]["ids"]:
                per_rel[i].append(t)
        for i in sorted(matched_all):
            date, ministry, title = meta[i]
            dt, dr = discovered_by.get(i, ("", ""))
            ts = per_rel[i]
            w.writerow([i, date, ministry, title, dt, dr, len(ts),
                        " | ".join(ts), URL % i])

    # 05 — round-by-round convergence
    with open(os.path.join(out, "05_round_summary.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["round", "terms_added", "new_releases_found",
                    "cumulative_releases", "pct_of_window"])
        for r in rounds:
            w.writerow([r["round"], r["terms_added"], r["new_releases"],
                        r["total_releases"],
                        "%.2f" % (100.0 * r["total_releases"] / window_n)])

    # 06 — the tree, for reading rather than filtering
    with open(os.path.join(out, "06_provenance_tree.txt"), "w") as f:
        f.write("PIB AI catalogue — provenance tree, %s..%s\n" % (WINDOW_LO, WINDOW_HI))
        f.write("=" * 78 + "\n")
        f.write("window: %d releases    AI pool: %d releases (%.1f%%)\n"
                % (window_n, len(matched_all), 100.0 * len(matched_all) / window_n))
        f.write(HINDI_NOTE + "\n")
        f.write("=" * 78 + "\n\n")
        children = collections.defaultdict(list)
        for t in order:
            p = terms[t].get("primary", "")
            if p:
                children[p].append(t)

        def walk(t, depth, seen):
            if t in seen or depth > 4:
                return
            seen.add(t)
            d = terms[t]
            f.write("%s%s  [%s, r%d, %d releases]\n"
                    % ("    " * depth, t, d["kind"], d["round"], len(d["ids"])))
            for c in sorted(children.get(t, []), key=lambda x: -len(terms[x]["ids"])):
                walk(c, depth + 1, seen)

        seen = set()
        for s in K1:
            walk(s, 0, seen)
            f.write("\n")

    print("\nartifacts:")
    for fn in sorted(os.listdir(out)):
        print("  %-34s %8d bytes" % (fn, os.path.getsize(os.path.join(out, fn))))


# Morphological channels are AI-shaped by construction (MausamGPT, CrimeGPT,
# a *bot name). A hit there is safe to accept automatically. Every other
# discovery channel — proximity names and phrases — is a candidate the user
# must promote, because those channels also surface Automobile, Samarth and
# "there was time". This is the human-in-the-loop boundary from the workplan.
AUTO_ACCEPT_CHANNELS = {"*GPT", "Smart*", "AI-*", "*Drishti", "*bot"}


def occurrences(rx, doc):
    """(match_count, first_offset) for a term regex in a document."""
    n = 0
    first = None
    for m in rx.finditer(doc):
        if first is None:
            first = m.start()
        n += 1
    return n, (first if first is not None else -1)


def persist(terms, order, matched_all, docs_map, discovered_by):
    """Materialise the catalogue into corpus.db as presentable, queryable data.

    - terms           : full vocabulary + candidates, with round/channel/parent
    - term_matches    : one row per (accepted term, release) with count+offset
    - term_parents    : the seed -> extended-term edges (the expansion tree)
    - v_* views        : one query each for the four deliverable screenshots
    Human-accepted rows keep their status; only channel/doc_freq are refreshed.
    """
    rw = sqlite3.connect(DB, timeout=60)
    cur = rw.cursor()

    # -- schema: a channel column, and the parent-edge table -----------------
    cols = set(r[1] for r in cur.execute("PRAGMA table_info(terms)"))
    if "channel" not in cols:
        cur.execute("ALTER TABLE terms ADD COLUMN channel TEXT")
    cur.execute("""CREATE TABLE IF NOT EXISTS term_parents (
                    child_term  TEXT, parent_term TEXT, round INTEGER,
                    docs_in_parent INTEGER,
                    PRIMARY KEY (child_term, parent_term))""")
    cur.execute("DELETE FROM term_matches")          # rebuilt below, in full
    cur.execute("DELETE FROM term_parents")

    now = datetime.now(timezone.utc).isoformat()
    prior = {r[0]: (r[1], r[2]) for r in cur.execute(
        "SELECT term, status, reviewed_by FROM terms")}

    accepted_terms = []
    n_t = n_c = 0
    for t in order:
        d = terms[t]
        ch = d["kind"]
        if t in prior and prior[t][0] == "accepted":
            status, who = "accepted", prior[t][1] or d.get("origin", "human")
            ch = d.get("origin", ch) if d["round"] == 0 else ch
        elif d["round"] == 0:
            status, who = "accepted", "seed"
        elif ch in AUTO_ACCEPT_CHANNELS:
            status, who = "accepted", "auto-morph"
        else:
            status, who = "candidate", "auto-k1"

        cur.execute("INSERT OR REPLACE INTO terms "
                    "(term, round, parent_term, status, reviewed_by, reviewed_at, "
                    " lift_score, doc_freq, channel, note) "
                    "VALUES (?,?,?,?,?,?,?,?,?,COALESCE((SELECT note FROM terms WHERE term=?),?))",
                    (t, d["round"], d.get("primary") or None, status, who, now,
                     None, len(d["ids"]), ch, t, ch))
        if status == "accepted":
            accepted_terms.append(t)
            n_t += 1
        else:
            n_c += 1
        for p, c in d["parents"].items():
            cur.execute("INSERT OR REPLACE INTO term_parents VALUES (?,?,?,?)",
                        (t, p, d["round"], c))

    # -- term_matches for the accepted vocabulary, with count + offset -------
    # FTS matches on the raw body, which still contains the PIB URLs we strip
    # before mining. A release whose only occurrence of a term sits inside such
    # a URL is not a real mention, so we confirm every FTS hit with a whole-word
    # scan of the cleaned text and drop the zero-count ones. doc_freq is then
    # set to this confirmed count so the terms table and term_matches agree.
    n_m = 0
    for t in accepted_terms:
        rx = re.compile(r"\b" + re.escape(t).replace(r"\ ", r"\s+") + r"\b", re.I)
        batch = []
        for i in terms[t]["ids"]:
            cnt, off = occurrences(rx, docs_map.get(i, ""))
            if cnt == 0:
                continue
            batch.append((t, i, cnt, off))
        cur.executemany(
            "INSERT OR REPLACE INTO term_matches "
            "(term, relid, match_count, first_offset) VALUES (?,?,?,?)", batch)
        cur.execute("UPDATE terms SET doc_freq=? WHERE term=?", (len(batch), t))
        n_m += len(batch)

    # -- the four screenshot views ------------------------------------------
    build_views(cur)

    rw.commit()
    cur.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    rw.close()
    print("\ncorpus.db written:")
    print("  terms          : %d accepted, %d candidates" % (n_t, n_c))
    print("  term_matches   : %d (accepted term x release) rows" % n_m)
    print("  views          : v_accepted_keywords, v_keyword_yield, "
          "v_hits_by_year, v_ai_pool")


def build_views(cur):
    for v in ("v_accepted_keywords", "v_keyword_yield", "v_hits_by_year",
              "v_ai_pool", "v_expansion_tree"):
        cur.execute("DROP VIEW IF EXISTS %s" % v)

    # 2. accepted keyword list
    cur.execute("""
        CREATE VIEW v_accepted_keywords AS
        SELECT term, round, channel,
               COALESCE(parent_term,'(seed)') AS parent_term,
               reviewed_by, doc_freq AS releases_matched
        FROM terms WHERE status='accepted'
        ORDER BY round, doc_freq DESC, term""")

    # 4. per-keyword yield (releases identified by each keyword)
    cur.execute("""
        CREATE VIEW v_keyword_yield AS
        SELECT t.term, t.round, t.channel,
               COALESCE(t.parent_term,'(seed)') AS parent_term,
               COUNT(m.relid) AS releases_matched,
               SUM(m.match_count) AS total_mentions
        FROM terms t
        LEFT JOIN term_matches m ON m.term=t.term
        WHERE t.status='accepted'
        GROUP BY t.term
        ORDER BY releases_matched DESC, t.term""")

    # 1 & 3. AI hits / matched releases per year (+ a TOTAL row)
    cur.execute("""
        CREATE VIEW v_hits_by_year AS
        SELECT year, ai_releases, ai_mentions FROM (
            SELECT substr(r.release_date,1,4) AS year,
                   COUNT(DISTINCT m.relid)   AS ai_releases,
                   COUNT(*)                  AS ai_mentions,
                   1 AS ord
            FROM term_matches m JOIN releases r ON r.relid=m.relid
            GROUP BY year
            UNION ALL
            SELECT 'TOTAL',
                   COUNT(DISTINCT m.relid),
                   COUNT(*), 2
            FROM term_matches m
        ) ORDER BY ord, year""")

    # the deduplicated AI pool: one row per release, with what caught it
    cur.execute("""
        CREATE VIEW v_ai_pool AS
        SELECT r.relid, r.release_date, r.ministry_raw, r.title,
               COUNT(m.term)               AS n_terms,
               GROUP_CONCAT(m.term, ' | ') AS matched_terms
        FROM term_matches m JOIN releases r ON r.relid=m.relid
        GROUP BY r.relid
        ORDER BY r.release_date""")

    # the expansion tree: each extended term under the ONE seed that most
    # strongly surfaced it (terms.parent_term = strongest-overlap parent).
    # Showing every co-occurrence edge instead makes popular terms appear under
    # every seed, which hides which seed actually did the work.
    cur.execute("""
        CREATE VIEW v_expansion_tree AS
        SELECT parent_term AS seed, term AS extended_term,
               round, channel, status, doc_freq AS releases_matched
        FROM terms
        WHERE round>=1 AND parent_term IS NOT NULL
        ORDER BY parent_term, status, doc_freq DESC""")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--max-rounds", type=int, default=4)
    r.add_argument("--no-write-db", dest="write_db", action="store_false",
                   default=True)
    r.set_defaults(func=run)
    a = ap.parse_args()
    a.func(a)
