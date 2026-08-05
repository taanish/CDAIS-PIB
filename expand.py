#!/usr/bin/env python3
"""
Iterative keyword expansion over the local PIB corpus.

Deliberately LIBERAL: candidates are surfaced if they look AI-adjacent at all.
Frequency lift only orders the review queue — it never excludes. Precision is
recovered later at the classification stage; recall lost here is lost for good.

    python3 expand.py round --year 2025          # match accepted terms, mine candidates
    python3 expand.py accept "term a" "term b"    # promote candidates
    python3 expand.py reject "term c"
    python3 expand.py terms                       # show current list
"""
import argparse
import collections
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "corpus.db")

# ---------------------------------------------------------------- seed list --
SEEDS = [
    "AI", "ML", "artificial intelligence", "intelligent", "smart", "automated",
    "algorithm", "chatbot", "facial recognition", "face recognition", "FRT",
    "ANPR", "predictive", "analytics", "machine learning", "deep learning",
    "Safe City", "SafeCity", "Bhashini", "Drishti",
]

# Morphological shapes that signal AI/automation but that a whole-word search
# cannot express. These generate CANDIDATES, they are not themselves terms.
#
# Dropped after round 0 on 2025: e-/i-*, *Setu/Mitra, *Vision/Netra produced 74
# of 76 candidates and nearly all were noise — they match Indian government
# digital-programme naming conventions (e-rickshaws, Ram Setu, "long-term
# vision"), which track digitisation rather than AI. Named-system discovery is
# handled by the proximity channel below instead.
MORPH = [
    (r"\b([A-Za-z]{2,}GPT)\b",                       "*GPT"),
    (r"\b(Smart[A-Z][A-Za-z]{2,})\b",                "Smart*"),
    (r"\b([A-Za-z]{3,}[-–]AI|AI[-–][A-Za-z]{3,})\b", "AI-*"),
    (r"\b([A-Z][A-Za-z]{2,}\s?Drishti)\b",           "*Drishti"),
    (r"\b([A-Za-z]{2,}[-–]?(?:bot|Bot))\b",          "*bot"),
    (r"\b([A-Z][a-z]+[A-Z][A-Za-z]{2,})\b",          "camelCase"),
]

# Proximity channel: a capitalised name sitting near an accepted AI term AND
# described as a system. The descriptor is what separates "Divya Drishti tool"
# from "Shri Jitendra Singh" — person names are never followed by "platform".
SYSTEM_WORD = re.compile(
    r"^(?:platform|portal|system|systems|app|application|tool|toolkit|mission|"
    r"model|engine|dashboard|chatbot|bot|software|module|suite|framework|"
    r"initiative|scheme|programme|program|project|solution|technology)\b", re.I)
HONORIFIC = set("shri smt sh dr prof mr mrs ms hon hon'ble shrimati kumari".split())
CAPSEQ = re.compile(r"\b([A-Z][A-Za-z0-9]{2,}(?:\s+[A-Z][A-Za-z0-9]{2,}){0,3})\b")

# Words that are never useful as AI signals, however often they co-occur.
STOP = set("""the a an and or of in to for on at by with from as is are was were be been
being this that these those it its his her their our your my we you they he she
i has have had do does did will would shall should may might can could must not
no nor but if then than so such also more most other some any all both each few
own same too very s t don now d ll m o re ve y ain shri smt dr shri. km lakh crore
government india indian ministry department minister union state states national
new delhi press information bureau said says today year years month months day days
also including various total per cent percent number one two three four five""".split())

MINISTRY_WORDS = set("""ministry department secretariat commission council authority
board bureau office cabinet committee corporation institute organisation organization""".split())


def connect():
    if not os.path.exists(DB):
        sys.exit("no corpus at %s" % DB)
    return sqlite3.connect("file:%s?mode=ro" % DB, uri=True)


def rw_connect():
    return sqlite3.connect(DB, timeout=60)


def term_regex(t):
    """Whole-word, case-insensitive, whitespace-flexible — mirrors PIB search."""
    return re.compile(r"\b" + re.escape(t).replace(r"\ ", r"\s+") + r"\b", re.I)


def load_terms(con):
    rows = con.execute("SELECT term, status, round FROM terms").fetchall()
    if not rows:
        return None
    return rows


def ensure_seeds(rw):
    have = set(r[0] for r in rw.execute("SELECT term FROM terms"))
    now = datetime.now(timezone.utc).isoformat()
    for t in SEEDS:
        if t not in have:
            rw.execute("INSERT INTO terms (term, round, status, reviewed_by, reviewed_at) "
                       "VALUES (?,0,'accepted','seed',?)", (t, now))
    rw.commit()


def load_docs(con, year=None):
    sql = "SELECT relid, COALESCE(title,''), COALESCE(body_text,'') FROM releases"
    args = ()
    if year:
        sql += " WHERE release_date LIKE ?"
        args = (str(year) + "%",)
    return [(r[0], r[1] + " \n " + r[2]) for r in con.execute(sql, args)]


def match_terms(docs, terms):
    """-> {term: set(relid)}"""
    out = {}
    for t in terms:
        rx = term_regex(t)
        out[t] = set(i for i, d in docs if rx.search(d))
    return out


MIN_LIFT = 3.0   # relevance gate for plain n-grams only; patterns bypass it
TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9'’]{1,}")


def grams_of(text, maxn=3):
    """Lowercased 1..maxn grams for one document, as a set (doc-frequency use)."""
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


def mine(docs, matched_ids, accepted, topn=60, min_in=3, max_share=0.25):
    """Liberal candidate generation.

    Two passes, so we never rescan the corpus per candidate:
      1. harvest candidates from the matched subset only, prune rare ones
      2. one sweep over the whole corpus to get each survivor's doc frequency
    """
    inset = [(i, d) for i, d in docs if i in matched_ids]
    acc_lower = set(a.lower() for a in accepted)
    surface = {}            # lowercase key -> nicest surface form seen
    kind = {}
    in_docs = collections.defaultdict(set)

    # --- pass 1a: morphological shapes (the high-value channel)
    for pat, label in MORPH:
        rx = re.compile(pat)
        for i, d in inset:
            for m in rx.findall(d):
                w = (m if isinstance(m, str) else m[0]).strip()
                if len(w) < 3:
                    continue
                k = w.lower()
                in_docs[k].add(i)
                surface.setdefault(k, w)
                kind.setdefault(k, label)

    # --- pass 1a2: proximity channel — named systems near an accepted term
    acc_rx = [term_regex(t) for t in accepted]
    for i, d in inset:
        windows = []
        for rx in acc_rx:
            for m in rx.finditer(d):
                windows.append(d[max(0, m.start() - 120):m.end() + 120])
        for seg in windows:
            for name in CAPSEQ.findall(seg):
                nm = re.sub(r"\s+", " ", name).strip()
                toks = nm.lower().split()
                if toks[0] in HONORIFIC or toks[0] in STOP or toks[-1] in STOP:
                    continue
                if any(t in MINISTRY_WORDS for t in toks):
                    continue
                # must be described as a system right after the name
                after = seg[seg.find(nm) + len(nm):].lstrip(" ,.'’()")
                if not SYSTEM_WORD.match(after):
                    continue
                k = nm.lower()
                in_docs[k].add(i)
                surface.setdefault(k, nm)
                kind.setdefault(k, "near-AI name")

    # --- pass 1b: n-grams from the matched subset
    for i, d in inset:
        for g in grams_of(d):
            in_docs[g].add(i)
            surface.setdefault(g, g)
            kind.setdefault(g, "%d-gram" % (g.count(" ") + 1))

    # prune: must appear in a few matched docs, and not already accepted
    keep = {k for k, ids in in_docs.items()
            if len(ids) >= min_in and k not in acc_lower}
    if not keep:
        return [], inset

    # --- pass 2: one corpus sweep for doc frequency of survivors
    corpus_docs = collections.defaultdict(set)
    for i, d in docs:
        for g in grams_of(d) & keep:
            corpus_docs[g].add(i)
    # morphological candidates aren't n-grams, so count them by regex once each
    for k in keep:
        if kind.get(k, "").endswith("gram"):
            continue
        rx = term_regex(surface[k])
        corpus_docs[k] = set(i for i, d in docs if rx.search(d))

    n_docs = len(docs)
    outset_n = max(1, n_docs - len(inset))
    rows = []
    for k in keep:
        cids = corpus_docs.get(k, set())
        new_ids = cids - matched_ids
        if not new_ids:
            continue                                  # adds nothing new
        if len(cids) > max_share * n_docs:
            continue                                  # boilerplate, not a signal
        p_in = len(in_docs[k]) / max(1, len(inset))
        p_out = max(1, len(new_ids)) / outset_n
        rows.append({"term": surface[k], "kind": kind.get(k, "?"),
                     "in_matched": len(in_docs[k]), "corpus": len(cids),
                     "new": len(new_ids), "lift": p_in / p_out if p_out else 0.0,
                     "new_ids": new_ids})

    # Two channels, deliberately treated differently.
    #
    #   patterns  - morphological shapes (Smart*, *GPT, *bot ...). These ARE the
    #               liberal channel: shown regardless of statistics, because a
    #               name like MausamGPT is a signal even if it appears twice.
    #   ngrams    - ordinary phrases. Ranked by novelty but gated on lift, or the
    #               queue fills with "sabha" and "narendra modi", which add the
    #               most new documents precisely because they mean nothing.
    pats = [r for r in rows if not r["kind"].endswith("gram")]
    ngrams = [r for r in rows if r["kind"].endswith("gram") and r["lift"] >= MIN_LIFT]
    pats.sort(key=lambda r: (-r["lift"], -r["new"]))
    ngrams.sort(key=lambda r: (-r["lift"], -r["new"]))
    return pats, ngrams[:topn], inset


def excerpt(docs_map, relid, term, width=52):
    d = docs_map.get(relid, "")
    m = term_regex(term).search(d)
    if not m:
        return ""
    s = d[max(0, m.start() - width):m.end() + width]
    return re.sub(r"\s+", " ", s).strip()


def cmd_round(args):
    con = connect()
    rw = rw_connect()
    ensure_seeds(rw)
    accepted = [r[0] for r in con.execute("SELECT term FROM terms WHERE status='accepted'")]
    docs = load_docs(con, args.year)
    docs_map = dict(docs)
    all_ids = set(i for i, _ in docs)
    print("\ncorpus: %d releases%s" % (len(docs), " (%s)" % args.year if args.year else ""))
    print("accepted terms: %d\n" % len(accepted))

    per = match_terms(docs, accepted)
    matched = set().union(*per.values()) if per else set()

    print("%-26s %7s %7s" % ("term", "hits", "unique"))
    print("-" * 44)
    for t in sorted(per, key=lambda x: -len(per[x])):
        others = set().union(*[v for k, v in per.items() if k != t]) if len(per) > 1 else set()
        print("%-26s %7d %7d" % (t[:26], len(per[t]), len(per[t] - others)))
    print("-" * 44)
    print("%-26s %7d  (%.1f%% of corpus)\n" % ("UNION", len(matched),
                                               100.0 * len(matched) / max(1, len(docs))))

    pats, ngrams, inset = mine(docs, matched, accepted, topn=args.top, min_in=args.min_in)

    def show(title, rows, note):
        print("\n" + "=" * 84)
        print("%s  (%d)" % (title, len(rows)))
        print(note)
        print("%-3s %-30s %-12s %5s %5s %6s" % ("#", "candidate", "kind", "new", "corp", "lift"))
        print("-" * 84)
        for n, r in enumerate(rows, 1):
            print("%-3d %-30s %-12s %5d %5d %6.1f"
                  % (n, r["term"][:30], r["kind"], r["new"], r["corpus"], r["lift"]))
            ex = excerpt(docs_map, sorted(r["new_ids"])[0], r["term"])
            if ex:
                print("    ... %s" % ex[:100])

    show("A. PATTERN CANDIDATES", pats,
         "shown regardless of statistics - a name like MausamGPT counts even at n=2")
    show("B. PHRASE CANDIDATES", ngrams,
         "ranked by association (lift >= %.0f); novelty alone surfaces generic PIB words" % MIN_LIFT)
    con.close()
    rw.close()


def cmd_accept(args):
    rw = rw_connect()
    now = datetime.now(timezone.utc).isoformat()
    rnd = (rw.execute("SELECT COALESCE(MAX(round),0) FROM terms").fetchone()[0] or 0) + 1
    for t in args.terms:
        rw.execute("INSERT OR REPLACE INTO terms (term, round, status, reviewed_by, reviewed_at) "
                   "VALUES (?,?,'accepted','human',?)", (t, rnd, now))
    rw.commit()
    print("accepted %d term(s) into round %d" % (len(args.terms), rnd))


def cmd_reject(args):
    rw = rw_connect()
    now = datetime.now(timezone.utc).isoformat()
    for t in args.terms:
        rw.execute("INSERT OR REPLACE INTO terms (term, round, status, reviewed_by, reviewed_at) "
                   "VALUES (?,-1,'rejected','human',?)", (t, now))
    rw.commit()
    print("rejected %d term(s)" % len(args.terms))


def cmd_terms(args):
    con = connect()
    for st in ("accepted", "rejected"):
        rows = [r[0] for r in con.execute("SELECT term FROM terms WHERE status=? ORDER BY round, term", (st,))]
        print("\n%s (%d): %s" % (st.upper(), len(rows), ", ".join(rows) if rows else "-"))
    print()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("round"); r.add_argument("--year"); r.add_argument("--top", type=int, default=60); r.add_argument("--min-in", dest="min_in", type=int, default=3)
    r.set_defaults(func=cmd_round)
    a = sub.add_parser("accept"); a.add_argument("terms", nargs="+"); a.set_defaults(func=cmd_accept)
    j = sub.add_parser("reject"); j.add_argument("terms", nargs="+"); j.set_defaults(func=cmd_reject)
    t = sub.add_parser("terms"); t.set_defaults(func=cmd_terms)
    args = ap.parse_args()
    args.func(args)
