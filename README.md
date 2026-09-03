# CDAIS — PIB AI-Deployment Catalogue

A systematic, auditable catalogue of when the Indian government says it is using
artificial intelligence, built from Press Information Bureau (PIB) press releases,
2003–2026. Every entry is backed by the exact release that proves it.

This repository holds the **code and documentation**. The data itself — the
~1.3 GB `corpus.db` database — is too large for GitHub and is shared separately
(see [The data](#the-data)).

---

## Status (September 2026)

- **Stage 1 — Download the releases: COMPLETE.** `corpus.db` holds **241,604**
  English releases spanning 2003–2026. About 51,000 further ids were checked and
  found to be genuine gaps (no release at that id).
- **Stage 2 — Find the ones that mention AI: COMPLETE.** A vocabulary of **229**
  accepted AI keywords, grown by repeated human-reviewed expansion rounds until
  nothing new surfaced. Which keyword matched which release is recorded; the AI
  candidate pile is queryable as the `v_ai_pool` view.
- **Stage 3 — Sort real AI use from AI mentioned in passing: IN PROGRESS.** A
  written rulebook (`rulebook.md`) defines the scheme (system / mention / not AI,
  plus sub-types). A machine prototype (Claude Sonnet) classified the most recent
  window as a worked example; human review of the wider back-catalogue is underway.

---

## How the pieces fit

The work runs in three stages, and the files group the same way.

**Stage 1 — download** (`crawl.py` and friends)
Walks every release id on the PIB archive, parses each page, and stores it.
Rate-governed, resumable, and guarded against recording real releases as missing
when PIB's servers are flaky.
- `crawl.py` — the downloader / parser
- `supervise.sh` / `start.sh` / `stop.sh` — run and babysit it (pauses when PIB is unhealthy, resumes when it recovers)
- `status.py` — live status readout (`python3 status.py --all`)
- `schema.sql` — the database structure; `ministries.sql` — the ministry name list

**Stage 2 — find AI mentions** (`catalogue.py`, `expand.py`)
Searches the downloaded text for approved AI words, then hunts inside the matches
for new AI words to add, with a human approving every one. Repeats until nothing
new turns up.
- `catalogue.py` — the search / expand / filter loop
- `expand.py` — approve or reject terms
- `filter_v2.py`, `find_polluters.py`, `drop_polluters.py` — candidate filtering
- `review.py`, `apply_review.py`, `build_review.py`, `build_reconsider.py`, `assess_review.py`, `build_keyword_review.py` — the term-review tooling
- `screenshots.sh` — prints the summary tables

**Stage 3 — classify deployments** (`rulebook.md`, `stage3_prototype/`)
Reads each AI-mentioning release and decides whether it reports a real government
AI system, only mentions AI, or is a false match — with an evidence quote for
every call.
- `rulebook.md` — the classification rules
- `stage3_prototype/` — the prototype run: scripts (`prep.py`, `ingest.py`, `report.py`), outputs, and the human-review workbooks

**Documentation**
- `README.md` — this file
- `HANDOFF.txt` — detailed scraper and PIB-site notes (a historical snapshot from Aug 2026; see the banner inside)
- `scraper tldr` — engineering notes from the scraper build
- `rulebook.md` — the Stage-3 classification rules
- `cover_note.md` — a plain-English write-up of the keyword-filtering method
- `CLAUDE.md` — working conventions for this project

---

## The data

`corpus.db` (~1.3 GB) is **not in this repository** — GitHub cannot hold a file
that large. It contains all 241,604 releases, the keyword tagging, and the
classification tables.

Two ways to get it:
- **Shared copy** — the frozen database is stored separately *(location TBD)*.
  This is the canonical record: PIB edits and removes pages over time, so a fresh
  download would not reproduce it exactly.
- **Rebuild from scratch** — run `crawl.py` (see [Usage](#usage)). This is slow
  (days, subject to PIB's uptime) and produces a *later* corpus, not the same
  snapshot.

The repository does include small human-readable exports (`catalogue_2024_2026/`,
`stage3_prototype/*.csv`) and example releases (`sample20_*`) so you can see the
shape of the data without the full database.

---

## Things that will bite you (hard-won facts)

- **The search index does not fill itself.** `releases_fts` is an "external
  content" index. Until it is rebuilt, full-text searches silently return zero
  rows — no error. Rebuild with:
  `INSERT INTO releases_fts(releases_fts) VALUES('rebuild');`
- **PIB pastes full web links into the release body text.** Strip links before
  searching for words, or link fragments look like invented product names.
- **Search matches whole words only.** Searching "GPT" does not find "ChatGPT" —
  that is why the vocabulary also hunts word shapes.
- **"intelligence" is a trap.** It sits inside "artificial intelligence" but on
  its own drags in every Intelligence Bureau release. Blocked by hand.
- **PIB's own site search silently caps at 1,000 results** and drops the oldest
  matches — which is why we downloaded everything instead of relying on it.
- **PIB goes unhealthy for days** (15-second responses, real releases wrongly
  reported missing). The downloader detects this and waits rather than record
  false gaps.
- **Hindi is not included.** PIB's Hindi archive has no working search and
  corrupted encoding — deliberately excluded. The corpus is complete for
  *English* releases 2003–2026, not all PIB output.

---

## Usage

Open the database read-only (safe even while something else is writing):
```bash
sqlite3 "file:corpus.db?mode=ro"
```

Rebuild the database structure from scratch:
```bash
sqlite3 corpus.db < schema.sql && sqlite3 corpus.db < ministries.sql
```

Run the downloader (newest-first, survives sleep, resumable). Re-issuing the same
command resumes — any release already fetched is skipped; Ctrl-C commits the
current batch rather than discarding it:
```bash
caffeinate -is python3 crawl.py --db corpus.db 2>&1 | tee crawl.log
```

Live status:
```bash
python3 status.py --all
```

---

## Corpus scope

| | |
|---|---|
| Source | `archive.pib.gov.in/archive2/PrintRelease.aspx?relid=N` |
| relid range checked | 1 – 292,729 |
| Date span | Dec 2003 – 05 Aug 2026 |
| Stored | 241,604 English releases (the rest are genuine gaps or excluded non-English) |
| Language | English only |

**Excluded, and why.** Hindi (~155k docs) lives in a *separate relid space* with
no working advanced search — `AdvancesearchHindi.aspx` 404s. Hindi records that
leak into the English index have titles stored as literal ASCII `?` (server-side
Unicode loss) and their bodies 302-redirect to a 404. Urdu and Regional have the
same structural problem. Photos, Features, and Invitations are separate corpora.
Coverage is therefore *complete for English releases 2003–present*, not "all PIB
communications."

### relid → date anchors

| relid | date | | relid | date |
|---|---|---|---|---|
| 100 | 10-Dec-2003 | | 100,000 | 11-Oct-2013 |
| 1,000 | 07-Feb-2004 | | 180,000 | 16-Jun-2018 |
| 10,000 | 04-Jul-2005 | | 220,000 | 10-Mar-2021 |
| 60,000 | 31-Mar-2010 | | 260,000 | 19-Sep-2024 |
| 80,000 | 31-Jan-2012 | | 292,729 | 05-Aug-2026 |

## Why we downloaded everything instead of searching the site

PIB's Advanced Search has a hard, silent **1000-result cap** (50 pages × 20).
Page 51 returns empty and the "Next" link disappears — no warning, no total
count. Results are newest-first, so truncation always removes the oldest material.
Measured: a 2003–2026 search for `"artificial intelligence"` returned 1000 hits,
all from 2025–2026 — every hit from 2010, 2013 and 2016 was silently dropped.
Downloading everything removes the cap and the site's keyword blind spots, and
makes keyword expansion a free local operation that can run unlimited rounds.

## Other PIB-site behaviour worth knowing

- `PrintRelease.aspx?relid=N` is **stateless** — no cookies, no session. Three
  other URL patterns (`erelease.aspx`, `newsite/erelease.aspx`,
  `pib.gov.in/PressReleasePage.aspx?PRID=`) return HTTP 200 but ignore the id and
  serve unrelated pages. Do not trust a 200 there.
- Missing records return **302** → `mainpage.aspx` → 404. Recorded as `absent`.
- Advanced Search day = "All" silently returns zero results; its date filters are
  fuzzy by ~1 day (dedupe by relid).

## Rate limiting

No `robots.txt` exists, so there is no published crawl-delay. Measured latency:
~65–100 ms for PrintRelease. A bounded probe reached ~13.8 requests/second with
zero errors, and no ceiling was found. The crawler nonetheless starts at 5 req/s,
ramps to 10 after an hour of clean running, and halves its rate on latency drift
or any error.

---

*The full, detailed scraper and PIB-site notes — including the database schema,
example queries, and open items as of Aug 2026 — are in `HANDOFF.txt`.*
