-- PIB AI-deployment corpus — schema
-- Layers 1-2 (fetch provenance + release records) are written by the crawler.
-- Layers 3-4 (vocabulary, classification) are created here but populated later.

PRAGMA journal_mode = WAL;
PRAGMA synchronous  = NORMAL;

-- ---------------------------------------------------------------- Layer 1 --
-- One row per relid attempted. Never deleted; this is the audit trail.
CREATE TABLE IF NOT EXISTS fetch_log (
    relid          INTEGER PRIMARY KEY,
    url            TEXT    NOT NULL,
    http_status    INTEGER,              -- 200 ok | 302 missing record | other
    fetched_at     TEXT    NOT NULL,     -- ISO-8601 UTC
    elapsed_ms     INTEGER,
    byte_size      INTEGER,
    content_sha256 TEXT,
    parse_status   TEXT    NOT NULL,     -- ok | partial | failed | absent
    parse_warnings TEXT                  -- JSON array of strings
);
CREATE INDEX IF NOT EXISTS ix_fetch_status ON fetch_log(parse_status);

-- ---------------------------------------------------------------- Layer 2 --
CREATE TABLE IF NOT EXISTS releases (
    relid          INTEGER PRIMARY KEY REFERENCES fetch_log(relid),
    title          TEXT,
    heading        TEXT,                 -- centred sub-heading; often differs from title
    ministry_raw   TEXT,                 -- verbatim from <div id="thd1">
    ministry_id    INTEGER REFERENCES ministries(ministry_id),
    release_date   TEXT,                 -- ISO-8601 date, e.g. 2018-06-16
    release_time   TEXT,                 -- HH:MM (IST)
    body_text      TEXT,
    word_count     INTEGER,
    char_count     INTEGER,
    image_count    INTEGER,
    image_urls     TEXT,                 -- JSON array
    has_devanagari INTEGER NOT NULL DEFAULT 0,
    mojibake_ratio REAL    NOT NULL DEFAULT 0.0
);
CREATE INDEX IF NOT EXISTS ix_rel_date     ON releases(release_date);
CREATE INDEX IF NOT EXISTS ix_rel_ministry ON releases(ministry_id);

-- Controlled vocabulary lifted from the AdvSearch ministry dropdown (85 values).
CREATE TABLE IF NOT EXISTS ministries (
    ministry_id    INTEGER PRIMARY KEY,
    canonical_name TEXT NOT NULL
);
-- Populated in the QA pass, once the observed raw strings are known.
CREATE TABLE IF NOT EXISTS ministry_aliases (
    raw_string  TEXT PRIMARY KEY,
    ministry_id INTEGER REFERENCES ministries(ministry_id)
);

-- Full-text index over the corpus. Drives the keyword-expansion loop.
-- External-content table: stores no duplicate text, reads through to releases.
CREATE VIRTUAL TABLE IF NOT EXISTS releases_fts USING fts5(
    title, heading, body_text,
    content='releases',
    content_rowid='relid',
    tokenize='unicode61 remove_diacritics 2'
);

-- ---------------------------------------------------------------- Layer 3 --
CREATE TABLE IF NOT EXISTS terms (
    term        TEXT PRIMARY KEY,
    round       INTEGER NOT NULL,
    parent_term TEXT REFERENCES terms(term),
    status      TEXT    NOT NULL,        -- candidate | accepted | rejected
    reviewed_by TEXT,
    reviewed_at TEXT,
    lift_score  REAL,
    doc_freq    INTEGER,
    novel_docs  INTEGER,
    note        TEXT
);

CREATE TABLE IF NOT EXISTS term_matches (
    term         TEXT    REFERENCES terms(term),
    relid        INTEGER REFERENCES releases(relid),
    match_count  INTEGER,
    first_offset INTEGER,
    PRIMARY KEY (term, relid)
);
CREATE INDEX IF NOT EXISTS ix_tm_relid ON term_matches(relid);

-- ---------------------------------------------------------------- Layer 4 --
CREATE TABLE IF NOT EXISTS classification_runs (
    run_id         TEXT PRIMARY KEY,
    model_id       TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    prompt_sha256  TEXT NOT NULL,
    started_at     TEXT,
    finished_at    TEXT,
    doc_count      INTEGER
);

CREATE TABLE IF NOT EXISTS ai_classifications (
    relid              INTEGER REFERENCES releases(relid),
    run_id             TEXT    REFERENCES classification_runs(run_id),
    is_ai_relevant     INTEGER NOT NULL,
    is_substantive     INTEGER NOT NULL,
    mention_type       TEXT,
    lifecycle_stage    TEXT,
    deploying_body     TEXT,
    system_name        TEXT,
    application_domain TEXT,
    technology_type    TEXT,
    beneficiary_scale  TEXT,
    budget_mentioned   TEXT,
    evidence_quote     TEXT,
    evidence_start     INTEGER,
    evidence_end       INTEGER,
    confidence         REAL,
    PRIMARY KEY (relid, run_id)
);

-- Crawl-level bookkeeping so a resumed run can report on prior sessions.
CREATE TABLE IF NOT EXISTS crawl_sessions (
    session_id   TEXT PRIMARY KEY,
    started_at   TEXT NOT NULL,
    finished_at  TEXT,
    range_lo     INTEGER,
    range_hi     INTEGER,
    attempted    INTEGER DEFAULT 0,
    ok           INTEGER DEFAULT 0,
    absent       INTEGER DEFAULT 0,
    failed       INTEGER DEFAULT 0,
    notes        TEXT
);
