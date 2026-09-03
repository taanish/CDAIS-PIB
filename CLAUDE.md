# CDAIS — Indian Government AI Deployment Catalogue

## What this project is

We are building a list of every time the Indian government said it is using AI.
The source is PIB press releases (the official government press notices), 2003 to 2026.
Every entry has to be backed by the exact release that proves it, so the whole thing is auditable.

The user is a researcher, not a software engineer. He is the domain expert. He decides
scope and method. Claude builds and measures.

---

## How to talk to me — READ THIS FIRST

This is the rule that matters most on this project. It has been raised repeatedly.

**Write in plain English. Like you are explaining to a smart person who does not code.**

- Short sentences. One idea per sentence.
- No jargon. If a technical word is unavoidable, say what it means in plain words first.
- Words to avoid unless I ask for them: corpus, n-gram, lift, purity, channel, morphology,
  postings, parent term, precision, recall, yield, signal, downstream, gate, funnel.
- **No metaphors for technical things.** Saying a filter "decides what gets to reproduce"
  is not helpful. Say what it actually does.
- Use real examples with real numbers. "'take home ration' shows up in 43 releases, 23 of
  them AI ones" beats any abstract explanation.
- Prefer plain bullet lists. Do not reach for tables, diagrams or ASCII art unless I ask.
- Do not restate the same point three different ways. Say it once.

**If I say you are not making sense, do not defend the previous answer. Rewrite it simpler.**

---

## What not to do

- **Do not run code or data analysis when I ask you to think, plan, or explain.**
  If I say "walk me through", "help me understand", "think with me", or "planning mode",
  that means talk to me. No scripts, no measurements, no file edits. Ask first if unsure.
- **Do not write or change code until we have agreed on the design.** I want to understand
  the approach before it gets built.
- Do not use the Agent/subagent tool unless I ask for it.
- Do not invent thresholds and numbers. If a rule needs a number, say the number is a guess
  and say how we would measure the right one. I have pushed back on unjustified numbers
  more than once and I will again.
- Do not claim something works because it ran without an error. Check the output is real.
  (This has already burned us once — see the FTS index note below.)

## What to do

- Tell me when my reasoning is wrong. Say it in a sentence, then do what I asked anyway.
- Flag the weak parts of your own work honestly. I would rather hear "this is about half
  junk" than a confident summary.
- When something is a judgement call, say so and say which way you would go.

---

## The workflow

The project has three stages. Stage 3 is parked for now.

**Stage 1 — Download the press releases.** Mostly done.

**Stage 2 — Find the ones that mention AI.** This is the active work. It is a loop:

1. Search the releases using the AI words we have approved.
2. Everything found goes into the "AI pile". Record which word found which release.
3. Look inside the AI pile only, and hunt for possible new AI words. Three hunts run at once:
   - words shaped like AI words (ends in GPT, ends in bot, starts with Smart)
   - names sitting right next to an AI word and called a system/platform/tool
   - every run of one, two or three words in the text
4. Cut that list down with mechanical rules, so a person can actually read it.
5. **A human approves or rejects.** The code does not add words by itself, except the
   obviously AI-shaped ones.
6. Approved words join the list. Go back to step 1. Stop when a round finds nothing new.

**Stage 3 — Work out which mentions are real AI use versus AI talked about in passing.**
A codebook exists and was tested on 20 releases by hand. Not run at scale. Parked.

Key point about the loop: an approved word does two jobs next round. It finds new releases,
and its releases get hunted for more new words. So a bad word goes on to produce more bad
words. That is why the human approval step is not optional.

---

## Where things are

Everything is in `/Users/taanish/Desktop/CDAIS/PIB` (a git repo).

- `corpus.db` — the database. ~800 MB. All releases, all tagging, all views.
- `crawl.py` — downloads releases from PIB.
- `start.sh` / `stop.sh` / `supervise.sh` — start, stop, and babysit the downloader.
- `status.py` — dataset and download status. Run `python3 status.py --all`.
- `catalogue.py` — the stage 2 loop (searching, hunting, filtering).
- `expand.py` — older version of the same idea. Still used for approving words.
- `screenshots.sh` — prints the four summary tables for presenting.
- `HANDOFF.txt`, `scraper tldr` — written for handing the project to someone else.
  **HANDOFF.txt has a known error in it** (it claims an FTS query was verified; it was not).

Useful things already in the database, queryable directly:
`v_accepted_keywords`, `v_keyword_yield`, `v_hits_by_year`, `v_ai_pool`, `v_expansion_tree`.

---

## Hard-won facts — do not rediscover these

- **PIB pastes full web links into the body text of releases.** Bits of those links look
  like invented product names. Always strip links before hunting for words.
- **The search index inside corpus.db does not fill itself.** It is an "external content"
  index and needs an explicit rebuild command. It silently returned zero rows for a while
  and I wrongly reported that a query worked.
- **The word "intelligence" is the classic trap.** It sits inside "artificial intelligence",
  so it passes every mechanical test, but accepting it drags in every Intelligence Bureau
  release. Blocked by hand.
- **Searching for a word only matches whole words.** Searching "GPT" does not find "ChatGPT".
  That is why the word-shape hunt exists.
- **Government acronyms are everywhere and look like product names.** MoSPI, DoNER, MoHUA.
  A hunt based on capitalisation alone is useless — it was tried and removed.
- **PIB's own website search silently caps at 1000 results.** This is why we downloaded
  everything rather than relying on their search.
- **PIB goes unhealthy for days at a time** (15 second responses, and it wrongly reports
  real releases as missing). The downloader detects this and stops rather than record
  false gaps. `supervise.sh` waits it out and restarts automatically.
- Hindi releases are not in the corpus. PIB's Hindi archive was unreachable. English only.
