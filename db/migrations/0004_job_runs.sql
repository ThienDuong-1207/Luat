-- 0004: theo dõi lần chạy của các job build (spec 3.3, M11 mục 2; D-027).
-- crawl_runs chỉ ghi crawl; parse/extract/amend trước đây ghi quarantine không có run_id.
-- quarantine.run_id nay trỏ tới crawl_runs.run_id (stage crawl) hoặc job_runs.run_id (stage khác).

CREATE TABLE job_runs (
  run_id        uuid PRIMARY KEY,
  job           text NOT NULL CHECK (job IN ('build_silver','build_gold','build_index')),
  started_at    timestamptz NOT NULL,
  finished_at   timestamptz,
  status        text NOT NULL CHECK (status IN ('running','success','failed')),
  error         text,
  stats         jsonb NOT NULL DEFAULT '{}',
  -- độ tươi: lần crawl gần nhất của dữ liệu đầu vào, đo lúc job bắt đầu
  data_crawled_at timestamptz,
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now(),
  CHECK (finished_at IS NULL OR finished_at >= started_at)
);
CREATE INDEX job_runs_job_started_idx ON job_runs (job, started_at DESC);
CREATE INDEX quarantine_run_idx ON quarantine (run_id);

CREATE TRIGGER job_runs_set_updated_at BEFORE UPDATE ON job_runs
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();
