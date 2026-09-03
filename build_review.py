#!/usr/bin/env python3
"""
Build the human-review sheet for the chosen filter setting.

Pulls the agreed candidate set straight out of candidate_runs — no new
filtering, just the rules we already settled:
  - phrases: share >= 0.60 AND in >= 40 releases AND not redundant
  - shape/named hunts: everything (they skip the two tests by design)
For each term it attaches one real example sentence from an AI release, so a
reviewer can judge it without opening the database.

    python3 build_review.py                 # writes review_candidates.csv

The reviewer fills the DECISION column with 'keep' or 'drop' (leave blank to
skip for now), then apply_review.py reads it back.
"""
import csv
import os
import re
import sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "corpus.db")
RUN = "patch-v2-2024-2026"
OUT = os.path.join(HERE, "review_candidates.csv")
URL_RE = re.compile(r"https?://\S+|www\.\S+", re.I)

SHARE_MIN = 0.60
TOTAL_MIN = 40


def sentence_around(text, term):
    """A short, readable window of text around the first mention of `term`."""
    rx = re.compile(r"\b" + re.escape(term).replace(r"\ ", r"\s+") + r"\b", re.I)
    m = rx.search(text)
    if not m:
        return ""
    a = text.rfind(".", 0, m.start())
    b = text.find(".", m.end())
    a = a + 1 if a != -1 else max(0, m.start() - 90)
    b = b if b != -1 else min(len(text), m.end() + 90)
    return re.sub(r"\s+", " ", text[a:b]).strip()[:240]


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default=RUN)
    ap.add_argument("--out", default=OUT)
    args = ap.parse_args()
    run, out = args.run, args.out

    con = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)

    phrases = con.execute(
        "SELECT term, channel, in_pool, total, share FROM candidate_runs "
        "WHERE run_label=? AND status='candidate' AND channel LIKE '%phrase' "
        "AND redundant=0 AND share>=? AND total>=? ",
        (run, SHARE_MIN, TOTAL_MIN)).fetchall()
    shaped = con.execute(
        "SELECT term, channel, in_pool, total, share FROM candidate_runs "
        "WHERE run_label=? AND status='candidate' AND channel NOT LIKE '%phrase'",
        (run,)).fetchall()

    # group label controls review order: named systems first (highest value),
    # then AI-shaped words, then phrases by how many AI releases they touch.
    def group(ch):
        if ch == "named system":
            return (0, "named system")
        if ch.endswith("phrase"):
            return (2, "phrase")
        return (1, "AI-shaped word")

    rows = []
    for term, ch, inp, tot, share in shaped + phrases:
        g_ord, g_name = group(ch)
        rows.append((g_ord, -(inp or 0), term, g_name, ch, inp, tot, share))
    rows.sort()

    # attach one example sentence, pulled from the AI pool only
    pool_ids = [r[0] for r in con.execute("SELECT DISTINCT relid FROM term_matches")]
    docs = {}
    q = ("SELECT relid, COALESCE(title,''), COALESCE(body_text,'') FROM releases "
         "WHERE relid IN (%s)" % ",".join("?" * len(pool_ids)))
    for i, t, b in con.execute(q, pool_ids):
        docs[i] = URL_RE.sub(" ", t + " \n " + b)
    order = sorted(docs)

    def example(term):
        rx = re.compile(r"\b" + re.escape(term).replace(r"\ ", r"\s+") + r"\b", re.I)
        for i in order:
            if rx.search(docs[i]):
                return sentence_around(docs[i], term), i
        return "", ""

    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["DECISION (keep/drop)", "group", "term", "type",
                    "ai_releases", "total_releases", "pct_ai", "example_sentence",
                    "example_relid"])
        for _, _, term, g_name, ch, inp, tot, share in rows:
            ex, relid = example(term)
            w.writerow(["", g_name, term, ch, inp, tot,
                        "%d%%" % round((share or 0) * 100), ex, relid])

    con.close()
    n_named = sum(1 for r in rows if r[3] == "named system")
    n_shape = sum(1 for r in rows if r[3] == "AI-shaped word")
    n_phrase = sum(1 for r in rows if r[3] == "phrase")
    print("wrote %s" % out)
    print("  %d terms total" % len(rows))
    print("    named systems  : %d  (reviewed first)" % n_named)
    print("    AI-shaped words: %d" % n_shape)
    print("    phrases        : %d" % n_phrase)


if __name__ == "__main__":
    main()
