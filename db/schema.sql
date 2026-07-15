-- LabScope schema (proposal §5, extended with provenance/compliance fields)

CREATE TABLE IF NOT EXISTS instruments (
  id INTEGER PRIMARY KEY,
  manufacturer TEXT NOT NULL,
  model TEXT NOT NULL,
  model_aliases TEXT NOT NULL DEFAULT '[]',   -- JSON array
  category TEXT,
  principle TEXT,
  specs_json TEXT NOT NULL DEFAULT '{}',      -- {ranges, lod, response_time_s, notes, ...}
  specs_provenance TEXT DEFAULT 'curated',    -- 'curated' | 'datasheet'
  datasheet_url TEXT,
  status TEXT DEFAULT 'unknown',              -- 'current' | 'discontinued' | 'unknown'
  epa_designation TEXT,                       -- US EPA reference/equivalent method (roadmap 12.6)
  ccep_designation TEXT,                       -- China CCEP/MEE certification (roadmap 12.6)
  seed_confidence REAL DEFAULT 1.0,
  UNIQUE (manufacturer, model)
);

CREATE TABLE IF NOT EXISTS papers (
  id INTEGER PRIMARY KEY,
  doi TEXT UNIQUE,
  pmid TEXT,
  pmcid TEXT,
  openalex_id TEXT,
  title TEXT,
  year INTEGER,
  venue TEXT,
  fields TEXT DEFAULT '[]',                   -- JSON array of subject areas
  affiliations TEXT DEFAULT '[]',             -- JSON array of institution names
  citation_count INTEGER,
  oa_fulltext_source TEXT                     -- 'europepmc' | 'core' | 'openalex' | NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_papers_pmcid ON papers(pmcid) WHERE pmcid IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_papers_pmid ON papers(pmid) WHERE pmid IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_papers_openalex ON papers(openalex_id) WHERE openalex_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS instrument_paper (
  instrument_id INTEGER NOT NULL REFERENCES instruments(id),
  paper_id INTEGER NOT NULL REFERENCES papers(id),
  evidence_snippet TEXT,                      -- Methods sentence mentioning the model
  matched_alias TEXT,                         -- which alias/query produced the hit
  section TEXT,                               -- 'methods' | 'fulltext' | 'abstract' | NULL
  source TEXT,                                -- 'europepmc' | 'openalex' | 'core' | 's2'
  confidence REAL,                            -- 0-1 from the disambiguation pass
  PRIMARY KEY (instrument_id, paper_id)
);

CREATE TABLE IF NOT EXISTS listings (
  id INTEGER PRIMARY KEY,
  instrument_id INTEGER REFERENCES instruments(id),
  source TEXT NOT NULL,                       -- 'labx' | 'ebay' | 'manual' | ...
  title TEXT,
  price REAL,
  currency TEXT,
  condition TEXT,
  listing_url TEXT,
  scraped_at TEXT NOT NULL,
  UNIQUE (instrument_id, source, listing_url, scraped_at)
);

CREATE INDEX IF NOT EXISTS idx_ip_instrument ON instrument_paper(instrument_id);
CREATE INDEX IF NOT EXISTS idx_ip_paper ON instrument_paper(paper_id);
CREATE INDEX IF NOT EXISTS idx_listings_instrument ON listings(instrument_id);
