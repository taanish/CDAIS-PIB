# PIB AI-Deployment Corpus

Systematic corpus of English press releases from the Press Information Bureau
archive (`archive.pib.gov.in/archive2`), built to identify and catalogue
mentions of government AI deployments.

## Corpus scope

| | |
|---|---|
| Source | `archive.pib.gov.in/archive2/PrintRelease.aspx?relid=N` |
| relid range | 1 – 292,729 |
| Date span | Dec 2003 – present (rolling; relid 292,729 = 05-Aug-2026) |
| Expected documents | ~284,000 (≈97% of relid space; the rest are genuine gaps) |
| Language | English only |

**Excluded, and why.** Hindi (~155k docs) lives in a *separate relid space* with
no working advanced search — `AdvancesearchHindi.aspx` 404s in both `archive2/`
and `newsite/`. Hindi records that leak into the English index have titles
stored as literal ASCII `?` (server-side Unicode loss, not a client encoding
bug) and their bodies 302-redirect to a 404. Urdu and Regional have the same
structural problem. Photos, Features, and Invitations are separate corpora.

Coverage may therefore be described as *complete for English releases 2003–present*,
not "all PIB communications."

### relid → date anchors

| relid | date | | relid | date |
|---|---|---|---|---|
| 100 | 10-Dec-2003 | | 100,000 | 11-Oct-2013 |
| 1,000 | 07-Feb-2004 | | 180,000 | 16-Jun-2018 |
| 10,000 | 04-Jul-2005 | | 220,000 | 10-Mar-2021 |
| 60,000 | 31-Mar-2010 | | 260,000 | 19-Sep-2024 |
| 80,000 | 31-Jan-2012 | | 292,729 | 05-Aug-2026 |

## Why enumeration rather than keyword search

The archive's Advanced Search was reverse-engineered first and **rejected as a
discovery mechanism**. It has a hard, silent 1000-result cap (50 pages × 20).
Page 51 returns empty and the "Next" link simply disappears — no warning, no
total-count field. Results are newest-first, so truncation always removes the
oldest material.

Measured: a 2003–2026 search for `"artificial intelligence"` returned 1000 hits,
all with relids 280695–292729 — **2025–2026 only**. Every hit from 2010, 2013,
and 2016 was silently dropped. A keyword-driven pipeline would have produced a
confident-looking dataset missing two decades.

Enumeration removes the cap, the session-cursor pagination, the adaptive
date-slicing, and the keyword blind spots in one move — and makes keyword
expansion a free local operation that can run unlimited rounds.

## Other site behaviour worth knowing

- `PrintRelease.aspx?relid=N` is **stateless** — no cookies, no viewstate, no
  session. Three other URL patterns (`erelease.aspx`, `newsite/erelease.aspx`,
  `pib.gov.in/PressReleasePage.aspx?PRID=`) return HTTP 200 but ignore the id
  and serve unrelated pages. Do not trust a 200 here.
- Missing records return **302** → `mainpage.aspx` → 404. Recorded as `absent`.
- Advanced Search day = "All" (value `0`) silently returns zero results.
- Advanced Search date filters are fuzzy by ~1 day; dedupe by relid.

## Rate limiting

No `robots.txt` exists on either `archive.pib.gov.in` or `pib.gov.in` (both
serve the app's generic error page with a misleading 200), so there is no
published crawl-delay. Measured server latency: ~65–100 ms for PrintRelease,
~200–250 ms for the search callback.

A bounded escalation probe on PrintRelease reached **13.8 req/s sustained**
(~5.5 Mbps, 71 KB average pages) with zero errors and latency flat or better
than baseline — no ceiling was found; the limit hit was the serial test
harness, not the server.

The crawler nonetheless starts at **5 req/s and ramps to 10** after an hour of
clean running, and halves its rate on latency drift (>3× baseline median) or any
transport/HTTP error. The probe was a ~60-request burst, not a multi-hour crawl.

## Layout

```
schema.sql       four-layer schema + FTS5 index over the corpus
ministries.sql   85-value ministry controlled vocabulary (from the search form)
crawl.py         enumerator: rate governor, resume, parse, store
corpus.db        SQLite database (gitignored)
```

## Usage

```bash
# create/upgrade the database
sqlite3 corpus.db < schema.sql && sqlite3 corpus.db < ministries.sql

# dry run
python3 crawl.py --db corpus.db --hi 292729 --lo 292330 --limit 400

# full archive, newest-first, survives sleep
caffeinate -is python3 crawl.py --db corpus.db 2>&1 | tee crawl.log
```

Re-issuing the identical command resumes: any relid already in `fetch_log` is
skipped. Ctrl-C commits the current batch rather than discarding it.
