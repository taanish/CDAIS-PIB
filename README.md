# CDAIS — PIB AI-Deployment Catalogue

## What this project is

The Indian government frequently claims to be deploying artificial intelligence — in policing, welfare, agriculture, health, tax collection, and dozens of other domains. But there is no single, verified record of these deployments. 

This project builds that comprehensive record. The goal is to catalogue every AI system deployed by or on behalf of an Indian government authority, backed by the specific government document that proves it exists The source is the Press Information Bureau (PIB) archive -- PIB is the government's official press release service. It is the single largest searchable collection of what the government says it is doing.

This repository holds the code and documentation. The database itself (`corpus.db`, ~1.3 GB) is too large for GitHub and is available in [Releases](https://github.com/taanish/CDAIS-PIB/releases/tag/v1.0).

---

## How the method works

The work has three stages. 

### Stage 1 — Download the PIB archive

**The problem:** PIB Archive has a search function, but it  caps results at 1,000, and makes cataloguing the oldest matches extremely difficult. 

**The solution:** Download every English release in the archive spanning December 2003 to August 2026 and search locally.

### Stage 2 — Find the releases that mention AI

**The problem:** The government does not use a single consistent term for AI. Sometimes it says "AI" or "artificial intelligence" directly. Sometimes it uses technical terms like "ML" or "machine learning." Sometimes it reaches for adjacent language — "smart," "intelligent," "automated." And sometimes it uses specific product names like "BHASHINI" or "CrimeGPT" that no generic keyword would ever catch.

**The solution:** Build a keyword list iteratively, starting from a seed list of obvious terms ("AI," "artificial intelligence," "machine learning," "facial recognition," etc.) and expanding it in rounds. Here is how expansion works: 

- A traffic system found via "AI" turns out to also be described as "ANPR" (automatic number plate recognition) in a different release.
- A policing tool found via "artificial intelligence" appears elsewhere under "smart policing."
- A crop insurance system found via "ML" is described on a ministry page as "automated crop assessment."

Each of these new terms — ANPR, smart policing, automated crop assessment — gets added to the keyword list, and the search runs again. A human approves or rejects every addition. The process repeats until new rounds stop producing new terms.

The final list has 229 accepted keywords. The full expansion trail, which records which seed term led to which new term, and how many releases each one found, is recorded in the database and exported in `catalogue_2024_2026/`.

### Stage 3 — Classify each release

**The problem:** A release that contains the word "AI" is not necessarily about an AI deployment. A minister might mention AI in a speech about Digital India, or list it among a dozen buzzwords, or use a keyword like "smart" in a completely unrelated context ("smart city" planning that has nothing to do with AI). Most keyword-matched releases are not about real AI systems.

**The solution:** A human reads each matched release and classifies it using a simple test:

> **[a specific government body]** is **[running / building / buying / testing]** **[a specific AI tool]**

If all three blanks can be filled, it's a **system** — a real government AI deployment. If the release is about AI but any blank won't fill (no specific tool, no specific government operator, or the AI is only discussed rather than actually being deployed), it's a **mention**. If the keyword match was a false hit and the release isn't about AI at all, it's **not AI**.

The classification rules are in `rulebook.md`. Classification progress is tracked [here](https://docs.google.com/spreadsheets/d/1jb41T_YUZ33nX3pfcc6Tt7-tVAwvtdgTPB9f1jDvus0/edit?gid=628012928#gid=628012928).

---

## Current status (September 2026)

| Stage | Status |
|---|---|
| 1. Download | **Done.** 241,604 English releases in `corpus.db`, Dec 2003 – Aug 2026. |
| 2. Keyword filtering | **Vocabulary settled.** 229 keywords finalised. Applied to 2024–2026 (5,893 releases flagged); earlier years pending. |
| 3. Classification | **In progress.** Codebook written. Human review of flagged releases underway. |

---

## Preliminary findings

Classification of a one-month demo window (July 2026, 363 keyword-matched releases) shows the method's yield and noise rate:

- **74 real AI systems identified** across 11 domains, operated by 76 distinct government bodies.
- **70 mentions** — releases that discuss AI but don't describe a specific deployment.
- **219 not-AI** — false keyword matches (about 60% of all matches). This is expected: broad keywords like "smart" and "automated" cast a wide net, and the classification step is what separates signal from noise.

Of the 74 systems, 79% are already operational ("working"). The most common domains are health (16), governance and administration (15), environment and weather (12), policing and security (8), and transport (8). Technology types range from facial recognition and predictive models to chatbots, computer vision, and clinical decision support.

Examples of systems the keyword expansion surfaced that a basic search for "AI" would have missed: ANPR-based tolling systems (found via the expanded keyword "ANPR"), AI-driven vulnerability mapping in TB prevention (found via "AI" in a health ministry release but described using domain-specific language), and Poshan Tracker's face recognition system for welfare distribution (found via "facial recognition").

---

## Getting started

Download `corpus.db` from [Releases](https://github.com/taanish/CDAIS-PIB/releases/tag/v1.0) and place it in the repo root.

Open it read-only:
```bash
sqlite3 "file:corpus.db?mode=ro"
```

See all releases flagged as AI-mentioning:
```bash
sqlite3 "file:corpus.db?mode=ro" "SELECT * FROM v_ai_pool LIMIT 20;"
```

See the accepted keyword list:
```bash
sqlite3 "file:corpus.db?mode=ro" "SELECT * FROM v_accepted_keywords;"
```

Useful views already in the database: `v_ai_pool` (the flagged releases), `v_accepted_keywords` (the 229 terms), `v_keyword_yield` (how many releases each keyword found), `v_hits_by_year` (flagged releases per year).

---

## Files in this repository

**Stage 1 — Download**
- `crawl.py` — the downloader/parser
- `schema.sql` — database structure; `ministries.sql` — ministry name list

**Stage 2 — Keyword filtering**
- `catalogue.py` — the search, expansion, and filtering loop
- `screenshots.sh` — prints summary tables from the database views
- `catalogue_2024_2026/` — CSV exports of the keyword expansion results (readable without the database)

**Stage 3 — Classification**
- `rulebook.md` — the classification rules (the three-blank test described above)

**Other documentation**
- `cover_note.md` — detailed write-up of how the keyword filtering method was developed, including the thresholds used and what they miss

---

## Scope and limitations

The corpus is **English-language PIB releases only**. Hindi, Urdu, and Regional language archives were excluded because PIB's Hindi advanced search page returns a 404, and Hindi records that leak into the English index have corrupted encoding. This is a real gap — deployments announced only in Hindi are invisible to this method.

The keyword approach has a structural limitation described well in the project's internal strategy document: it can only find deployments that were publicly described using AI-adjacent language. It will miss systems that use AI but were never labelled as such (e.g., a "biometric matching" system described only in procurement documents), and it cannot independently verify whether something labelled as AI actually is (the "AI-washing" problem). These gaps are acknowledged, not solved.
