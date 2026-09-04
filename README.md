# CDAIS — PIB AI-Deployment Catalogue

A catalogue of AI systems reported in Indian government press releases, built from the Press Information Bureau (PIB) archive, 2003–2026. 

This repository contains the code and documentation. The database itself (`corpus.db`, ~1.3 GB) is too large for GitHub and is shared separately — see [The data](#the-data).

---

## Status (September 2026)

- **Stage 1 (download): Done.** `corpus.db` contains 241,604 English releases spanning 2003–2026.

- **Stage 2 (keyword filtering): Done.** 229 accepted AI-related keywords, built up through iterative human-reviewed expansion rounds until no new terms surfaced. Keyword–release pairs are stored and queryable via the `v_ai_pool` view.

- **Stage 3 (classification): In progress.** A codebook (`rulebook.md`) defines the classification schema for releases that surface when searching for AI keywords. The three classifications are: system, mention-only, or not-AI. 

---

## Repository structure

Files are organised by stage.

**Stage 1 — Download**

Downloads every text release from the PIB archive, parses the page, and stores it.

- `crawl.py` — downloader/parser
- `schema.sql` — database schema; `ministries.sql` — ministry name list

**Stage 2 — Keyword filtering** (`catalogue.py`)

A pre-determined seed list of relevant AI terms is set. catalogue.py Searches downloaded PIB releases for these AI-related terms, and then looks within the matched releases for candidate new terms. A human approves or rejects each candidate. Once approved, the term is added to the AI-keyword list, and is searched for through the corpus to surface releases that contains this word; In this releases, candidate terms are surfaced, and a human accepts/rejects them. The process repeats until the keyword list is saturated.

- `catalogue.py` — search/expand/filter loop
- `screenshots.sh` — summary table output

**Stage 3 — Classification** (`rulebook.md`)

Each AI-mentioning release is classified as reporting a real government AI deployment, merely mentioning AI, or being a false match. Every classification includes an evidence quote. This is a manual process. Find latest progress on classification here: https://docs.google.com/spreadsheets/d/1jb41T_YUZ33nX3pfcc6Tt7-tVAwvtdgTPB9f1jDvus0/edit?gid=628012928#gid=628012928 

- `rulebook.md` — classification codebook

**Documentation**

- `README.md` — this file
- `rulebook.md` — classification codebook
- `cover_note.md` — write-up of the keyword-filtering method

---

## The data

`corpus.db` (~1.3 GB) is **not in this repository**. It contains all 241,604 releases, keyword tags, and classification tables.

To get it:
- **Shared copy** — a frozen snapshot is stored separately *(location TBD)*. This is the canonical version; PIB edits and deletes pages over time, so a fresh crawl would not reproduce it exactly.

## Caveats

- **English only.** Hindi, Urdu, and Regional archives have broken search and corrupted encoding. The corpus covers English releases comprehensively, not all PIB output.

---

## Usage

Open the database read-only:
```bash
sqlite3 "file:corpus.db?mode=ro"
```

Rebuild schema from scratch:
```bash
sqlite3 corpus.db < schema.sql && sqlite3 corpus.db < ministries.sql
```
