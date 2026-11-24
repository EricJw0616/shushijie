-- 图书中台 PostgreSQL 16 + pgvector 初始 schema
-- 原则：PostgreSQL 是唯一主库；大文件走对象存储；不要 SQLite。
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE IF NOT EXISTS schema_migrations (
  version     text PRIMARY KEY,
  applied_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS books (
  code            text PRIMARY KEY,
  title           text NOT NULL,
  author          text DEFAULT '',
  publisher       text DEFAULT '',
  prototype       text DEFAULT '',
  prototype_name  text DEFAULT '',
  status          text DEFAULT '',
  form            text DEFAULT '',
  meta            jsonb NOT NULL DEFAULT '{}'::jsonb,
  deleted_at      timestamptz,
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS books_title_trgm ON books USING gin (title gin_trgm_ops);

CREATE TABLE IF NOT EXISTS jobs (
  id          text PRIMARY KEY,
  kind        text NOT NULL,
  status      text NOT NULL,
  progress    integer NOT NULL DEFAULT 0,
  book_code   text REFERENCES books(code) ON DELETE SET NULL,
  title       text DEFAULT '',
  steps       jsonb NOT NULL DEFAULT '[]'::jsonb,
  result      jsonb,
  error       text DEFAULT '',
  log         text DEFAULT '',
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS jobs_status_idx ON jobs(status, created_at DESC);
CREATE INDEX IF NOT EXISTS jobs_book_idx ON jobs(book_code);

CREATE TABLE IF NOT EXISTS operations (
  id          bigserial PRIMARY KEY,
  book_code   text,
  action      text NOT NULL,
  payload     jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS operations_book_idx ON operations(book_code, created_at DESC);

CREATE TABLE IF NOT EXISTS segments (
  id          text PRIMARY KEY,
  book_code   text NOT NULL REFERENCES books(code) ON DELETE CASCADE,
  seq         integer,
  chapter     text DEFAULT '',
  text        text NOT NULL DEFAULT '',
  anchor      text DEFAULT '',
  meta        jsonb NOT NULL DEFAULT '{}'::jsonb,
  search_text text DEFAULT '',
  search_tsv  tsvector GENERATED ALWAYS AS (to_tsvector('simple', coalesce(search_text, ''))) STORED
);
CREATE INDEX IF NOT EXISTS segments_book_seq_idx ON segments(book_code, seq);
CREATE INDEX IF NOT EXISTS segments_tsv_idx ON segments USING gin(search_tsv);

CREATE TABLE IF NOT EXISTS cards (
  id          text PRIMARY KEY,
  book_code   text NOT NULL REFERENCES books(code) ON DELETE CASCADE,
  type        text DEFAULT '',
  fields      jsonb NOT NULL DEFAULT '{}'::jsonb,
  raw         text DEFAULT '',
  anchor      text DEFAULT '',
  status      text DEFAULT '',
  search_text text DEFAULT '',
  search_tsv  tsvector GENERATED ALWAYS AS (to_tsvector('simple', coalesce(search_text, ''))) STORED
);
CREATE INDEX IF NOT EXISTS cards_book_type_idx ON cards(book_code, type);
CREATE INDEX IF NOT EXISTS cards_tsv_idx ON cards USING gin(search_tsv);

CREATE TABLE IF NOT EXISTS people (
  id          text PRIMARY KEY,
  book_code   text NOT NULL REFERENCES books(code) ON DELETE CASCADE,
  name        text NOT NULL,
  frequency   integer DEFAULT 0,
  evidence    text DEFAULT '',
  anchor      text DEFAULT '',
  meta        jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS people_book_idx ON people(book_code);
CREATE INDEX IF NOT EXISTS people_name_trgm ON people USING gin (name gin_trgm_ops);

CREATE TABLE IF NOT EXISTS entities (
  id          text PRIMARY KEY,
  book_code   text NOT NULL REFERENCES books(code) ON DELETE CASCADE,
  type        text DEFAULT '',
  label       text NOT NULL,
  meta        jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS entities_book_type_idx ON entities(book_code, type);
CREATE INDEX IF NOT EXISTS entities_label_trgm ON entities USING gin (label gin_trgm_ops);

CREATE TABLE IF NOT EXISTS kg_nodes (
  id          text PRIMARY KEY,
  book_code   text REFERENCES books(code) ON DELETE CASCADE,
  node_key    text DEFAULT '',
  type        text DEFAULT '',
  label       text NOT NULL,
  payload     jsonb NOT NULL DEFAULT '{}'::jsonb,
  search_text text DEFAULT '',
  search_tsv  tsvector GENERATED ALWAYS AS (to_tsvector('simple', coalesce(search_text, ''))) STORED,
  created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS kg_nodes_book_type_idx ON kg_nodes(book_code, type);
CREATE INDEX IF NOT EXISTS kg_nodes_payload_idx ON kg_nodes USING gin(payload);
CREATE INDEX IF NOT EXISTS kg_nodes_tsv_idx ON kg_nodes USING gin(search_tsv);

CREATE TABLE IF NOT EXISTS kg_edges (
  id              text PRIMARY KEY,
  book_code       text REFERENCES books(code) ON DELETE CASCADE,
  source_id       text NOT NULL,
  target_id       text NOT NULL,
  rel             text DEFAULT '',
  kind            text DEFAULT '',
  confidence      text DEFAULT '',
  evidence_anchor text DEFAULT '',
  evidence_text   text DEFAULT '',
  payload         jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS kg_edges_source_idx ON kg_edges(source_id);
CREATE INDEX IF NOT EXISTS kg_edges_target_idx ON kg_edges(target_id);
CREATE INDEX IF NOT EXISTS kg_edges_book_kind_idx ON kg_edges(book_code, kind);

-- 1024 维与所选 embedding 模型绑定；换模型时新建表/列或重建，不要混维。
CREATE TABLE IF NOT EXISTS embeddings (
  id          bigserial PRIMARY KEY,
  owner_type  text NOT NULL,
  owner_id    text NOT NULL,
  book_code   text REFERENCES books(code) ON DELETE CASCADE,
  chunk_text  text NOT NULL DEFAULT '',
  embedding   vector(1024) NOT NULL,
  model       text NOT NULL,
  dim         integer NOT NULL DEFAULT 1024,
  created_at  timestamptz NOT NULL DEFAULT now(),
  UNIQUE (owner_type, owner_id, model)
);
CREATE INDEX IF NOT EXISTS embeddings_book_idx ON embeddings(book_code);
CREATE INDEX IF NOT EXISTS embeddings_hnsw ON embeddings
  USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);

CREATE TABLE IF NOT EXISTS files (
  id           text PRIMARY KEY,
  book_code    text REFERENCES books(code) ON DELETE SET NULL,
  object_key   text NOT NULL,
  filename     text DEFAULT '',
  content_type text DEFAULT '',
  bytes        bigint DEFAULT 0,
  sha256       text DEFAULT '',
  created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS files_book_idx ON files(book_code);

INSERT INTO schema_migrations(version) VALUES ('001_init')
ON CONFLICT (version) DO NOTHING;
