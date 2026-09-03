# Cover note — reworking how we pick candidate search words

**Quick context:** we find AI releases by searching with a list of AI words.
To grow that list, the machine reads the releases we have already caught and
suggests new words. A human approves every suggestion. This note is about the
step in between: how we cut the machine's suggestions down to a number a
human can actually review.

---

## What we started with

The first version had a set of rules for cutting down suggestions. Several
were arbitrary:

- a cap of 40 suggestions per search word — this is the only reason the old
  list looked small (787 words). Not good filtering, just a cap.
- a scoring rule that asked "does this phrase appear more densely inside AI
  releases than outside?" — sounds right, but non-AI releases outnumber AI
  ones five to one, and that imbalance breaks the comparison. Junk like
  "take home ration" (a food scheme) passed the test.
- smaller rules that threw away good words. Example: any phrase with a short
  word at its edge was binned, which killed real terms like "AI model".

## What happened when we removed the arbitrary rules

We binned the cap and the smaller arbitrary rules and re-ran. Result: about
2.3 million distinct words and phrases came out. Nobody can review millions.
So the cut-down step is necessary — the question is how to do it with rules
we can defend.

## The rework

A phrase now has to pass two tests, and it must pass both:

1. **Enough evidence.** The phrase must appear in at least N releases
   (counting all releases, AI or not). Why: phrases that appear in only 3
   releases score perfectly by pure luck — almost all of them are sentence
   fragments.
2. **Leans AI.** Of the releases containing the phrase, at least X% must be
   ones we have already flagged as AI. Why: this is the actual "is it about
   AI?" test, and unlike the old density rule it is not distorted by the
   size of the two piles.

We tested "pass either one" first: 14,000 survivors. Useless. "Pass both" is
what works.

## The numbers: words to review at each setting

Rows are the AI-lean test (X%), columns the evidence test (N releases).
Each cell = phrases a human would review, for 2024–2026:

| | 5+ releases | 10+ | 20+ | 40+ | 80+ |
|---|---|---|---|---|---|
| **50%** | 64,601 | 18,549 | 5,596 | 1,776 | 628 |
| **60%** | 41,121 | 9,305 | 2,463 | 666 | 205 |
| **70%** | 21,694 | 4,829 | 1,090 | **249** | 62 |
| **80%** | 16,440 | 2,658 | 535 | 93 | 20 |
| **90%** | 7,340 | 1,484 | 311 | 49 | 9 |

## The setting we picked

**70% AI-lean, at least 40 releases → 249 phrases.** Plus about 200 more
suggestions from two separate hunts that skip these tests on purpose:
words shaped like AI words (anything ending in "-GPT" or "-bot" — one
appearance is enough), and capitalised names described as a
system/platform/tool. Total for human review: **about 450. An afternoon.**

Being honest about the choice: 70/40 is where the list becomes reviewable,
not a number we have proven correct. Proving it is a half-day job — hand-label
a sample, check what each setting catches and misses. Not done yet.

## What came out — findings

- **It found real, named government AI systems** that no obvious search
  would ever catch: BharatGPT, ASHABot (health-worker chatbot), BHASHINI
  Sahayogi, Mission Mausam (weather), AgriStack (agriculture), Sarvam, and
  a proposed "Algorithm Auditing Framework". Finding names like these is the
  whole point of the iterative approach.
- **It found solid technical vocabulary we did not have:** cybersecurity,
  robotics, semiconductors, quantum computing, digital twin, deepfakes,
  large language models, supercomputing.
- **The strictness has a known price.** Requiring 40+ releases drops real
  but uncommon terms — "autonomous navigation" and "video surveillance
  system" are confirmed losses. Rare *named* systems still get in through
  the shape hunt, but a rare plain-English term does not. We accepted this
  trade for now.
- **About half the 249 is still junk, in three visible kinds:** fragments of
  phrases we already have ("artificial" on its own), officials' names that
  travel with AI events ("Abhishek Singh"), and skills/policy language
  ("reskilling", "hackathons") that is AI-adjacent but will not find
  deployments. The first two are fixable with two small rules. The third is
  a scope question: are we cataloguing AI deployments only, or all AI
  activity? That decision is not ours to make alone.

## Next

1. Human review of the ~450.
2. Hand-label a sample to put 70/40 on solid ground.
3. Re-run the loop with the approved words until it finds nothing new.
4. Then the next stage: a rulebook to separate releases that merely *talk*
   about AI from ones describing an actual deployed system. Draft exists,
   hand-tested on 20 releases; the grey zones (what counts as "deployed",
   whether funded-but-not-operated counts) need a group decision.
