-- 0001_init: toàn bộ bảng spec mục 6.
-- Các điểm lệch so với spec được ghi trong docs/DECISIONS.md (D-002..D-005).

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS unaccent;
CREATE EXTENSION IF NOT EXISTS btree_gist;

-- unaccent() là STABLE nên không dùng được trong generated column/index.
-- Bọc lại thành IMMUTABLE với dictionary chỉ định rõ (D-002). Truy vấn search cũng dùng hàm này.
CREATE OR REPLACE FUNCTION f_unaccent(text) RETURNS text
  LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT
  AS $$ SELECT public.unaccent('public.unaccent'::regdictionary, $1) $$;

-- Tự cập nhật updated_at
CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger
  LANGUAGE plpgsql AS $$
BEGIN
  NEW.updated_at := now();
  RETURN NEW;
END $$;

-- ===================== 6.1 Crawl state =====================
CREATE TABLE crawl_runs (
  run_id           uuid PRIMARY KEY,
  started_at       timestamptz NOT NULL,
  finished_at      timestamptz,
  status           text NOT NULL CHECK (status IN ('running','success','partial','blocked','failed')),
  discovered       int DEFAULT 0,
  detail_ok        int DEFAULT 0,
  pdf_downloaded   int DEFAULT 0,
  errors           int DEFAULT 0,
  selector_version text NOT NULL,
  created_at       timestamptz NOT NULL DEFAULT now(),
  updated_at       timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE crawl_queue (
  vbpl_id         bigint NOT NULL,
  stage           text NOT NULL CHECK (stage IN ('discover','detail','download')),
  url             text NOT NULL,
  status          text NOT NULL CHECK (status IN ('pending','done','failed','skipped')),
  retry_count     int NOT NULL DEFAULT 0,
  last_error      text,
  content_hash    text,
  first_seen_at   timestamptz NOT NULL,
  last_crawled_at timestamptz,
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (vbpl_id, stage)
);
CREATE INDEX crawl_queue_stage_status_idx ON crawl_queue (stage, status);

-- ===================== 6.2 Văn bản =====================
CREATE TABLE documents (
  vbpl_id           bigint PRIMARY KEY,
  so_hieu           text NOT NULL,
  ten_van_ban       text NOT NULL,
  loai_van_ban      text,
  co_quan_ban_hanh  text,
  nguoi_ky          text,
  ngay_ban_hanh     date,
  ngay_hieu_luc     date,
  ngay_het_hieu_luc date,
  tinh_trang        text,
  tinh_trang_norm   text CHECK (tinh_trang_norm IN
                      ('con_hieu_luc','het_hieu_luc','het_hieu_luc_mot_phan','chua_co_hieu_luc','unknown')),
  source_url        text NOT NULL,
  needs_reparse     boolean NOT NULL DEFAULT true,   -- D-004
  first_seen_at     timestamptz NOT NULL,
  last_crawled_at   timestamptz NOT NULL,
  created_at        timestamptz NOT NULL DEFAULT now(),
  updated_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX documents_so_hieu_idx ON documents (so_hieu);

-- D-003: khoá (sha256, vbpl_id) để một file đính kèm ở nhiều văn bản không mất liên kết.
CREATE TABLE document_files (
  sha256         text NOT NULL,
  vbpl_id        bigint NOT NULL REFERENCES documents,
  file_type      text NOT NULL CHECK (file_type IN ('pdf','html_fulltext')),
  object_key     text NOT NULL,
  size_bytes     bigint,
  has_text_layer boolean,
  downloaded_at  timestamptz NOT NULL,
  created_at     timestamptz NOT NULL DEFAULT now(),
  updated_at     timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (sha256, vbpl_id)
);

CREATE TABLE document_relations (
  src_vbpl_id   bigint NOT NULL,
  dst_vbpl_id   bigint,
  dst_so_hieu   text NOT NULL,
  relation_type text NOT NULL CHECK (relation_type IN
                  ('sua_doi','bi_sua_doi','thay_the','bi_thay_the','huong_dan','duoc_huong_dan','bai_bo')),
  origin        text NOT NULL CHECK (origin IN ('metadata_tab','parsed_text')),
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (src_vbpl_id, dst_so_hieu, relation_type)
);

-- ===================== 6.3 Điều khoản và phiên bản =====================
CREATE TABLE provisions (
  provision_id  text PRIMARY KEY,
  vbpl_id       bigint NOT NULL REFERENCES documents,
  provision_key text NOT NULL,
  level         text NOT NULL CHECK (level IN ('phan','chuong','muc','dieu','khoan','diem')),
  number        text NOT NULL,
  title         text,
  text          text NOT NULL,
  parent_id     text,
  ordinal       int NOT NULL,
  pdf_page      int,
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX provisions_vbpl_idx ON provisions (vbpl_id, ordinal);
CREATE INDEX provisions_key_idx ON provisions (provision_key);

CREATE TABLE amendments (
  amendment_id      text PRIMARY KEY,
  amending_vbpl_id  bigint NOT NULL,
  target_so_hieu    text NOT NULL,
  target_key        text NOT NULL,
  action            text NOT NULL CHECK (action IN ('sua_doi','bo_sung','bai_bo','unsupported')),
  new_text          text,
  effective_date    date NOT NULL,
  raw_instruction   text NOT NULL,
  parse_status      text NOT NULL CHECK (parse_status IN ('ok','needs_review')),
  created_at        timestamptz NOT NULL DEFAULT now(),
  updated_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX amendments_target_idx ON amendments (target_key, effective_date);

CREATE TABLE provision_versions (
  provision_key   text NOT NULL,
  version_no      int  NOT NULL,
  text            text,
  source_vbpl_id  bigint NOT NULL,
  valid_from      date NOT NULL,
  valid_to        date NOT NULL DEFAULT '9999-12-31',
  is_current      boolean NOT NULL,
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (provision_key, version_no),
  CHECK (valid_from < valid_to),
  -- D-005: DB cũng chặn hai version chồng lấn (lưới an toàn sau quality check của build_gold)
  EXCLUDE USING gist (provision_key WITH =, daterange(valid_from, valid_to, '[)') WITH &&)
);

-- ===================== 6.4 Hành vi vi phạm =====================
CREATE TABLE violations (
  violation_id        text PRIMARY KEY,
  provision_key       text NOT NULL,
  version_no          int NOT NULL,
  hanh_vi             text NOT NULL,
  phuong_tien         text[] NOT NULL,
  doi_tuong           text,
  muc_phat_min        bigint,
  muc_phat_max        bigint,
  tru_diem_gplx       int,
  tuoc_gplx_min_thang int,
  tuoc_gplx_max_thang int,
  bien_phap_bo_sung   text[],
  attributes          jsonb NOT NULL DEFAULT '{}',
  valid_from          date NOT NULL,
  valid_to            date NOT NULL,
  extraction_method   text NOT NULL CHECK (extraction_method IN ('regex','llm','manual')),
  confidence          real,
  needs_review        boolean NOT NULL DEFAULT false,
  created_at          timestamptz NOT NULL DEFAULT now(),
  updated_at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX violations_provision_idx ON violations (provision_key, version_no);
CREATE INDEX violations_validity_idx ON violations (valid_from, valid_to);
CREATE INDEX violations_attributes_idx ON violations USING gin (attributes);

-- ===================== 6.5 Chunks cho RAG =====================
CREATE TABLE chunks (
  chunk_id        text PRIMARY KEY,
  provision_key   text NOT NULL,
  version_no      int NOT NULL,
  vbpl_id         bigint NOT NULL,
  so_hieu         text NOT NULL,
  hierarchy_path  text NOT NULL,
  embed_text      text NOT NULL,
  display_text    text NOT NULL,
  embedding       vector(1024),
  tsv             tsvector GENERATED ALWAYS AS (to_tsvector('simple', f_unaccent(embed_text))) STORED,
  valid_from      date NOT NULL,
  valid_to        date NOT NULL,
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX chunks_embedding_idx ON chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX chunks_tsv_idx ON chunks USING gin (tsv);
CREATE INDEX chunks_validity_idx ON chunks (valid_from, valid_to);
CREATE INDEX chunks_provision_idx ON chunks (provision_key, version_no);

-- ===================== 6.6 Chất lượng, sự kiện, feedback =====================
CREATE TABLE quarantine (
  id          bigserial PRIMARY KEY,
  stage       text NOT NULL CHECK (stage IN ('crawl','parse','extract','amend')),
  entity_ref  text NOT NULL,
  rule        text NOT NULL,
  detail      jsonb,
  run_id      uuid,
  resolved    boolean DEFAULT false,
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX quarantine_open_idx ON quarantine (stage, resolved);

CREATE TABLE qa_sessions (
  session_id  uuid PRIMARY KEY,
  question    text NOT NULL,
  as_of_date  date NOT NULL,
  slots       jsonb NOT NULL DEFAULT '{}',
  status      text NOT NULL CHECK (status IN ('answered','need_clarification','not_found')),
  answer      jsonb,
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE qa_topic_counts (
  window_start     timestamptz NOT NULL,
  window_end       timestamptz NOT NULL,
  topic            text NOT NULL,
  n_questions      int NOT NULL,
  n_thumbs_down    int NOT NULL,
  updated_batch_id bigint NOT NULL,
  created_at       timestamptz NOT NULL DEFAULT now(),
  updated_at       timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (window_start, topic)
);

-- Gắn trigger updated_at cho mọi bảng
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY[
    'crawl_runs','crawl_queue','documents','document_files','document_relations',
    'provisions','amendments','provision_versions','violations','chunks',
    'quarantine','qa_sessions','qa_topic_counts']
  LOOP
    EXECUTE format(
      'CREATE TRIGGER %I BEFORE UPDATE ON %I FOR EACH ROW EXECUTE FUNCTION set_updated_at()',
      t || '_set_updated_at', t);
  END LOOP;
END $$;
