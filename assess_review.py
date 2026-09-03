#!/usr/bin/env python3
"""Assess a first-pass review: what was kept, what was dropped, and the
decisions most worth a second look — in both directions."""
import os, re, sqlite3, collections

HERE = os.path.dirname(os.path.abspath(__file__))
RUN = "patch-v2-2024-2026"

# words that read as AI on sight — used ONLY to flag drops worth re-checking,
# never to change anyone's decision.
AI_STEM = re.compile(r"(gpt|chatbot|\bbot\b|llm|neural|machine learn|deep learn|"
    r"algorith|generat|autonom|predict|cognit|recogni|facial|biometric|"
    r"language model|comput vision|analyt|drishti|bhashini|anpr|deepfake|"
    r"robot|drone|sensor|semantic|annotation|inference|forecast|synthetic|"
    r"digital twin|large language|multimodal|agentic|transformer)", re.I)
# words that read as NOT-AI (org / policy / person / generic) — used to flag
# keeps worth re-checking.
ORG = re.compile(r"(ministry|department|secretary|mission|scheme|portal|fund|"
    r"council|programme|program|division|meity|mospi|corporation|authority|"
    r"summit|congress|conference|award|hackathon|workshop|skilling|reskilling)", re.I)
AI_OK_ACRONYM = {"AI", "ML", "LLM", "OCR", "ANPR", "FRT", "FRS", "GPU", "NLP",
                 "HPC", "IOT", "AGI"}

rev = sqlite3.connect("file:%s?mode=ro" % os.path.join(HERE, "reviews.db"), uri=True)
dec = dict(rev.execute("SELECT term, decision FROM review_decisions"))
rev.close()

con = sqlite3.connect("file:%s?mode=ro" % os.path.join(HERE, "corpus.db"), uri=True)
meta = {}
for term, ch, inp, tot, sh in con.execute(
        "SELECT term, channel, in_pool, total, share FROM candidate_runs WHERE run_label=?",
        (RUN,)):
    meta[term] = (ch, inp, tot, sh)
con.close()

keep = {t: meta.get(t, ("?", 0, 0, 0)) for t, d in dec.items() if d == "keep"}
drop = {t: meta.get(t, ("?", 0, 0, 0)) for t, d in dec.items() if d == "drop"}


def kind(ch):
    if ch == "named system": return "named"
    if ch and ch.endswith("phrase"): return "phrase"
    return "shaped"


print("=" * 70)
print("FIRST-PASS REVIEW — ASSESSMENT")
print("=" * 70)
print("kept %d   dropped %d   (of %d decided)" % (len(keep), len(drop), len(keep) + len(drop)))
kc = collections.Counter(kind(v[0]) for v in keep.values())
dc = collections.Counter(kind(v[0]) for v in drop.values())
print("\n              kept   dropped   keep-rate")
for g in ("named", "shaped", "phrase"):
    tot = kc[g] + dc[g]
    print("  %-8s   %4d   %5d      %d%%" % (g, kc[g], dc[g], round(100 * kc[g] / tot) if tot else 0))

print("\n" + "-" * 70)
print("A) KEPT but reads as NOT-AI  (org / policy / person / bare acronym)")
print("   -> check these are really AI vocabulary, not just AI-adjacent")
print("-" * 70)
flag_keep = []
for t, (ch, inp, tot, sh) in keep.items():
    bare_acr = re.fullmatch(r"[A-Z]{2,6}s?", t) and t not in AI_OK_ACRONYM
    if ORG.search(t) or bare_acr:
        flag_keep.append((t, ch, inp, tot, sh))
for t, ch, inp, tot, sh in sorted(flag_keep, key=lambda x: -x[3]):
    print("  %-30s %-7s %4d/%-4d  %d%%" % (t[:30], kind(ch), inp, tot, round(sh * 100)))
if not flag_keep:
    print("  (none — your keeps all look like genuine AI terms)")

print("\n" + "-" * 70)
print("B) DROPPED but reads as AI  (AI-shaped word, named system, or AI phrase)")
print("   -> check you didn't bin a real term")
print("-" * 70)
flag_drop = []
for t, (ch, inp, tot, sh) in drop.items():
    if kind(ch) in ("named", "shaped") or AI_STEM.search(t):
        flag_drop.append((t, ch, inp, tot, sh))
for t, ch, inp, tot, sh in sorted(flag_drop, key=lambda x: -x[3])[:60]:
    print("  %-30s %-7s %4d/%-4d  %d%%" % (t[:30], kind(ch), inp, tot, round(sh * 100)))
print("  ... %d flagged drops total" % len(flag_drop))

print("\n" + "-" * 70)
print("C) EVERYTHING YOU KEPT  (your AI vocabulary so far)")
print("-" * 70)
for g in ("named", "shaped", "phrase"):
    terms = sorted(t for t, v in keep.items() if kind(v[0]) == g)
    print("\n  %s (%d):" % (g.upper(), len(terms)))
    line = "   "
    for t in terms:
        if len(line) + len(t) + 2 > 100:
            print(line); line = "   "
        line += t + ",  "
    if line.strip():
        print(line)
