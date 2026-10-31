# LuậtGT: Hệ thống thu thập văn bản luật giao thông và hỏi đáp có trích dẫn

> **Tài liệu thiết kế hệ thống (System Design Spec) dùng để giao cho AI code.**
> Môn: Big Data Analytics (72ITDS40303), Đại học Văn Lang. Nhóm 01.
> Phiên bản: v1.0 (20/10/2026)

---

## 0. Hướng dẫn cho AI coding assistant (đọc trước khi code)

1. **Làm theo thứ tự Milestone ở mục 14.** Không nhảy bước. Mỗi milestone có tiêu chí nghiệm thu; chỉ chuyển sang milestone sau khi tiêu chí trước đã đạt và có test.
2. **Không đoán CSS selector của vbpl.vn.** Trang có bot detection và cấu trúc HTML chưa được xác nhận. Milestone 1 bắt buộc lưu HTML mẫu (fixtures) bằng Playwright, rồi mới viết selector dựa trên fixtures đó. Mọi selector đặt trong `config/sources/vbpl.yaml`, không viết cứng trong code.
3. **Không tìm cách vượt bot detection** (không xoay proxy, không giả mạo, không giải CAPTCHA). Nếu bị chặn, crawler dừng, ghi log và báo lỗi.
4. **Mọi bước ghi dữ liệu phải idempotent:** chạy lại N lần cho cùng kết quả, không sinh bản trùng.
5. **Không xoá dữ liệu Bronze.** Bronze là nguồn để replay khi sửa lỗi parser.
6. Ngôn ngữ: Python 3.11+ cho backend/pipeline, TypeScript cho frontend. Có type hints, docstring ngắn, test bằng `pytest`.
7. Mọi tham số (đường dẫn, rate limit, model, ngưỡng) đặt trong file config hoặc biến môi trường, không viết cứng.
8. Khi một quyết định trong tài liệu này không khả thi trên thực tế (ví dụ trang không có tab nào đó), dừng lại, ghi rõ vấn đề vào `docs/DECISIONS.md` và đề xuất phương án, không tự ý đổi kiến trúc.

---

## 1. Mục tiêu và phạm vi

### 1.1. Driving question
Làm sao xây một pipeline biến văn bản pháp luật (HTML toàn văn + PDF gốc, liên tục bị sửa đổi) thành dữ liệu có cấu trúc và có phiên bản, để trả lời câu hỏi của người dân **theo đúng phiên bản luật có hiệu lực tại thời điểm hỏi**, kèm trích dẫn Điều/Khoản/Điểm?

### 1.2. Chức năng chính
1. **Thu thập:** crawl trang chi tiết văn bản trên vbpl.vn: metadata, toàn văn HTML, file PDF gốc.
2. **Xử lý:** tách cấu trúc Chương/Mục/Điều/Khoản/Điểm; trích xuất hành vi vi phạm và mức phạt; liên kết văn bản sửa đổi; dựng bảng phiên bản theo thời gian hiệu lực.
3. **Hỏi đáp:** người dùng đặt câu hỏi; hệ thống tìm điều khoản liên quan, trả lời có trích dẫn.
4. **Câu hỏi phụ:** khi câu hỏi chưa đủ thông tin (loại xe, nồng độ cồn, thời điểm vi phạm…), hệ thống đưa ra các lựa chọn để người dùng chọn, sinh từ dữ liệu có cấu trúc.
5. **Phân tích hành vi:** log câu hỏi/feedback xử lý bằng Spark Structured Streaming, hiển thị dashboard.

### 1.3. Phạm vi giai đoạn 1 (seed list)

| Văn bản | Vai trò |
|---|---|
| Luật Giao thông đường bộ 26/2001/QH10 | **Chỉ để thử crawler** (đã hết hiệu lực); ví dụ phiên bản đã đóng |
| Luật Trật tự, an toàn giao thông đường bộ 36/2024/QH15 | Luật chính |
| Luật 118/2025/QH15 (sửa đổi Luật 36/2024) | Văn bản sửa đổi |
| Luật Đường bộ 35/2024/QH15 | Luật chính |
| Nghị định 168/2024/NĐ-CP | Xử phạt VPHC giao thông đường bộ, trừ điểm GPLX |
| Nghị định 238/2026/NĐ-CP (hiệu lực 15/8/2026) | Sửa đổi NĐ 168/2024 |
| Nghị định 151/2024/NĐ-CP và NĐ 184/2025/NĐ-CP | Hướng dẫn Luật 36/2024 và văn bản sửa đổi |

> Seed list nằm ở `config/seed_documents.yaml`. Nhóm phải tự tra ID vbpl.vn của từng văn bản và xác nhận lại tình trạng hiệu lực trên trang trước khi chạy.

### 1.4. Ngoài phạm vi
- Tư vấn pháp lý. Mọi câu trả lời hiển thị disclaimer "Thông tin tra cứu, không thay thế tư vấn pháp lý".
- Crawl các trang tư nhân (thuvienphapluat, luatvietnam…).
- Tự động hợp nhất các câu sửa đổi phức tạp ("thay cụm từ… bằng…"): giai đoạn 1 chỉ xử lý *sửa đổi / bổ sung / bãi bỏ* điểm, khoản, điều; các dạng khác đưa vào hàng đợi xử lý tay.

---

## 2. Đặc điểm nguồn dữ liệu: vbpl.vn

### 2.1. Những gì đã biết
- URL mẫu:
  `https://vbpl.vn/van-ban/chi-tiet/luat-giao-thong-duong-bo-so-26-2001-qh10--23289?tabs=toan-van`
- Cấu trúc URL: `https://vbpl.vn/van-ban/chi-tiet/{slug}--{vbpl_id}?tabs={tab}`
  - `{slug}`: chỉ để đọc, có thể đổi; **không dùng làm khoá**.
  - `{vbpl_id}`: số nguyên (ví dụ `23289`), **dùng làm khoá chính** của văn bản.
  - `tabs=toan-van`: tab toàn văn dạng HTML (đã xác nhận có).
- Trang **có bot detection**: request HTTP đơn giản bị chặn. Phải dùng trình duyệt thật (Playwright, Chromium).
- Không có API công khai. Nguồn dữ liệu = HTML + file PDF đính kèm.

### 2.2. Những gì CHƯA biết (phải xác nhận ở Milestone 1)
- Tên các tab khác (thuộc tính, lược đồ/văn bản liên quan, văn bản gốc/PDF…) và giá trị tham số `tabs=` tương ứng.
- Vị trí và định dạng các trường metadata (số hiệu, ngày ban hành, ngày hiệu lực, tình trạng hiệu lực, cơ quan ban hành, người ký).
- Cách hiển thị danh sách văn bản liên quan (sửa đổi, bị sửa đổi, thay thế, hướng dẫn).
- Link tải PDF: link trực tiếp hay qua trang trung gian; PDF có lớp chữ hay là bản scan.
- Cấu trúc HTML toàn văn: Chương/Điều được đánh dấu bằng thẻ heading/class riêng hay chỉ là đoạn văn `<p>`.
- Trang tìm kiếm/danh sách: tham số tìm kiếm, phân trang.

### 2.3. Nguyên tắc với nguồn không có data contract (FDE Ch.5)
Nguồn có thể đổi giao diện bất kỳ lúc nào. Vì vậy:
- Selector trong YAML, có version (`selector_version`).
- Sau mỗi trang, chạy **schema check**; thiếu trường bắt buộc → đánh dấu lỗi, không ghi bản ghi thiếu.
- Lưu HTML gốc vào Bronze để có thể parse lại khi selector thay đổi.

---

## 3. Kiến trúc tổng thể

```
                        ┌─────────────────────────────────────────────┐
                        │      Airflow (orchestration, chạy hằng ngày) │
                        └─────────────────────────────────────────────┘
                                          │
 vbpl.vn ──(Playwright, rate-limited)──▶ [1] CRAWLER (3 tầng: discover → detail → download)
                                          │
                                          ▼
                    BRONZE (MinIO bucket `bronze`): HTML gốc, PDF gốc, metadata JSON
                                          │  [2] PARSE (Spark batch)
                                          ▼
                    SILVER (MinIO `silver`, Parquet): documents, provisions, relations, amendments
                                          │  [3] MODEL + EXTRACT (Spark + Python)
                                          ▼
                    GOLD (Parquet + PostgreSQL): provision_versions (SCD2), violations, chunks + vector
                                          │  [4] SERVING
                                          ▼
                    FastAPI ──▶ RAG + follow-up engine ──▶ Next.js web app
                                          │
                                          │  [5] EVENTS (câu hỏi, lựa chọn, feedback)
                                          ▼
                    events (file/Kafka) ──▶ Spark Structured Streaming (watermark) ──▶ Postgres ──▶ Dashboard
```

### 3.1. Tech stack

| Thành phần | Công nghệ | Ghi chú |
|---|---|---|
| Crawler | Python, Playwright (Chromium), BeautifulSoup/lxml | async, rate limit |
| Object storage | MinIO (tương thích S3) | lưu PDF/HTML (tránh small-files problem trên HDFS) |
| Xử lý batch | PySpark 4.x (local mode) | parse, extract, build Silver/Gold |
| Định dạng | Parquet | Silver/Gold |
| Serving DB | PostgreSQL 16 + pgvector + unaccent | truy vấn, vector search, full-text |
| Embedding | `BAAI/bge-m3` (sentence-transformers), dim 1024 | đa ngôn ngữ, có tiếng Việt |
| LLM | Interface `LLMClient` có thể đổi provider (Claude/OpenAI/local) | cấu hình qua env |
| PDF | PyMuPDF; OCR: Tesseract (`vie`) khi PDF là scan | |
| Backend | FastAPI, Pydantic v2, SQLAlchemy 2 | |
| Frontend | Next.js (App Router), TypeScript, Tailwind | phong cách Neo-brutalism (mục 15.3) |
| Streaming | Spark Structured Streaming; source mặc định = thư mục JSON, tuỳ chọn Kafka | áp dụng P09 |
| Orchestration | Apache Airflow 2.x | |
| Hạ tầng | Docker Compose | |
| Test | pytest, pytest-asyncio; Playwright test cho frontend (tuỳ chọn) | |

---

## 4. Cấu trúc thư mục repo

```
luatgt/
├── README.md
├── docker-compose.yml            # postgres(pgvector), minio, airflow, (kafka tuỳ chọn)
├── .env.example
├── pyproject.toml
├── config/
│   ├── settings.yaml             # rate limit, đường dẫn bucket, model, ngưỡng
│   ├── seed_documents.yaml       # danh sách văn bản giai đoạn 1
│   └── sources/
│       └── vbpl.yaml             # URL template, tên tab, CSS selector (có selector_version)
├── docs/
│   ├── DECISIONS.md              # ghi lại quyết định/thay đổi so với spec
│   └── SOURCE_NOTES.md           # ghi chú cấu trúc trang vbpl.vn sau khi khảo sát
├── src/luatgt/
│   ├── common/                   # config loader, logging, storage client (MinIO), db
│   ├── crawler/
│   │   ├── browser.py            # quản lý Playwright, rate limiter, retry, phát hiện bị chặn
│   │   ├── discover.py           # tầng 1
│   │   ├── detail.py             # tầng 2: metadata + toàn văn HTML + quan hệ
│   │   ├── download.py           # tầng 3: PDF
│   │   ├── selectors.py          # đọc vbpl.yaml, áp selector
│   │   ├── schema_check.py
│   │   └── state.py              # thao tác bảng crawl_queue / crawl_runs
│   ├── parsing/
│   │   ├── html_fulltext.py      # HTML toàn văn → cây điều khoản
│   │   ├── pdf_text.py           # PDF → text (+ OCR fallback), giữ số trang
│   │   ├── normalize.py          # Unicode NFC, khoảng trắng, header/footer
│   │   ├── structure.py          # regex Chương/Mục/Điều/Khoản/Điểm → tree
│   │   └── amendments.py         # parse câu "Sửa đổi, bổ sung điểm a khoản 4 Điều 18…"
│   ├── modeling/
│   │   ├── versions.py           # dựng provision_versions (SCD2)
│   │   └── violations.py         # trích xuất hành vi, mức phạt, trừ điểm…
│   ├── quality/
│   │   └── checks.py             # data quality rules + quarantine
│   ├── jobs/                     # entrypoint Spark job: build_silver.py, build_gold.py, build_index.py
│   ├── retrieval/
│   │   ├── embed.py
│   │   ├── search.py             # hybrid search + bộ lọc hiệu lực + RRF
│   │   └── rerank.py             # (tuỳ chọn)
│   ├── qa/
│   │   ├── followup.py           # thuật toán câu hỏi phụ
│   │   ├── answer.py             # gọi LLM, ép trích dẫn, kiểm tra trích dẫn
│   │   └── llm_client.py
│   ├── streaming/
│   │   └── qa_events_stream.py   # Spark Structured Streaming + watermark
│   └── api/
│       ├── main.py               # FastAPI app
│       ├── routes_ask.py
│       ├── routes_docs.py
│       ├── routes_feedback.py
│       └── routes_stats.py
├── dags/                         # Airflow DAGs
├── db/migrations/                # SQL migration (hoặc Alembic)
├── web/                          # Next.js frontend
├── eval/
│   ├── questions.yaml            # bộ câu hỏi đánh giá có đáp án chuẩn
│   └── run_eval.py
└── tests/
    ├── fixtures/vbpl/            # HTML/PDF mẫu lưu từ Milestone 1
    └── ...
```

---

## 5. Lưu trữ: Bronze / Silver / Gold

### 5.1. Bronze (MinIO bucket `bronze`), bất biến, chỉ thêm
```
bronze/
  html/{vbpl_id}/{tab}/{crawled_at_utc}__{sha256}.html
  pdf/{sha256}.pdf
  meta/{vbpl_id}/{crawled_at_utc}.json      # metadata thô trích từ trang + url + selector_version
```
- PDF đặt tên theo hash nội dung: tải lại cùng file → không ghi thêm.
- HTML lưu theo thời điểm crawl để có lịch sử; nếu hash trùng bản gần nhất thì không ghi.

### 5.2. Silver (MinIO `silver`, Parquet, phân vùng theo `vbpl_id`)
- `documents`, `document_files`, `document_relations`, `provisions`, `amendments`.

### 5.3. Gold
- Parquet: `provision_versions`, `violations`, `chunks`.
- Nạp vào PostgreSQL để phục vụ API (bảng ở mục 6). Nạp theo kiểu **upsert theo khoá** (idempotent).

> **Ghi chú liên hệ P01 (HDFS):** PDF luật chỉ vài trăm KB, nhỏ hơn rất nhiều block 128 MB của HDFS. Lưu hàng nghìn file nhỏ trên HDFS gây small-files problem (NameNode giữ metadata mọi file trong RAM). Vì vậy file gốc để trên object storage; Silver/Gold là Parquet khối lớn. Ghi lại số liệu (số file, tổng dung lượng, kích thước trung bình) để làm evidence trong báo cáo.

---

## 6. Data model (PostgreSQL)

> Viết dưới dạng SQL migration trong `db/migrations/`. Tất cả bảng có `created_at`, `updated_at` (timestamptz).

### 6.1. Crawl state
```sql
CREATE TABLE crawl_runs (
  run_id          uuid PRIMARY KEY,
  started_at      timestamptz NOT NULL,
  finished_at     timestamptz,
  status          text NOT NULL,          -- running | success | partial | blocked | failed
  discovered      int DEFAULT 0,
  detail_ok       int DEFAULT 0,
  pdf_downloaded  int DEFAULT 0,
  errors          int DEFAULT 0,
  selector_version text NOT NULL
);

CREATE TABLE crawl_queue (
  vbpl_id         bigint NOT NULL,
  stage           text NOT NULL,          -- discover | detail | download
  url             text NOT NULL,
  status          text NOT NULL,          -- pending | done | failed | skipped
  retry_count     int NOT NULL DEFAULT 0,
  last_error      text,
  content_hash    text,                   -- hash nội dung lần crawl gần nhất
  first_seen_at   timestamptz NOT NULL,
  last_crawled_at timestamptz,
  PRIMARY KEY (vbpl_id, stage)
);
```

### 6.2. Văn bản
```sql
CREATE TABLE documents (
  vbpl_id           bigint PRIMARY KEY,
  so_hieu           text NOT NULL,        -- "168/2024/NĐ-CP"
  ten_van_ban       text NOT NULL,
  loai_van_ban      text,                 -- Luật | Nghị định | Thông tư | ...
  co_quan_ban_hanh  text,
  nguoi_ky          text,
  ngay_ban_hanh     date,                 -- event time của văn bản
  ngay_hieu_luc     date,                 -- thời điểm bắt đầu áp dụng
  ngay_het_hieu_luc date,
  tinh_trang        text,                 -- nguyên văn trên trang
  tinh_trang_norm   text,                 -- con_hieu_luc | het_hieu_luc | het_hieu_luc_mot_phan | chua_co_hieu_luc | unknown
  source_url        text NOT NULL,
  first_seen_at     timestamptz NOT NULL, -- ingestion time lần đầu
  last_crawled_at   timestamptz NOT NULL  -- processing time gần nhất
);

CREATE TABLE document_files (
  sha256        text PRIMARY KEY,
  vbpl_id       bigint REFERENCES documents,
  file_type     text NOT NULL,            -- pdf | html_fulltext
  object_key    text NOT NULL,
  size_bytes    bigint,
  has_text_layer boolean,                 -- PDF có lớp chữ hay scan
  downloaded_at timestamptz NOT NULL
);

CREATE TABLE document_relations (
  src_vbpl_id   bigint NOT NULL,
  dst_vbpl_id   bigint,                   -- null nếu chưa crawl được văn bản đích
  dst_so_hieu   text NOT NULL,
  relation_type text NOT NULL,            -- sua_doi | bi_sua_doi | thay_the | bi_thay_the | huong_dan | duoc_huong_dan | bai_bo
  origin        text NOT NULL,            -- metadata_tab | parsed_text
  PRIMARY KEY (src_vbpl_id, dst_so_hieu, relation_type)
);
```

### 6.3. Điều khoản và phiên bản (SCD Type 2)
**Khoá điều khoản** (`provision_key`) có dạng ổn định theo văn bản gốc:
`{so_hieu_chuan}/D{dieu}[/K{khoan}][/P{diem}]`, ví dụ `ND168-2024/D18/K4/Pa`.
(`so_hieu_chuan`: bỏ dấu, thay `/` bằng `-`; điểm "đ" ghi là `Pdd`.)

```sql
CREATE TABLE provisions (                 -- nội dung NGUYÊN BẢN trong từng văn bản
  provision_id  text PRIMARY KEY,         -- {vbpl_id}:{path}
  vbpl_id       bigint NOT NULL REFERENCES documents,
  provision_key text NOT NULL,
  level         text NOT NULL,            -- chuong | muc | dieu | khoan | diem
  number        text NOT NULL,            -- "18", "4", "a"
  title         text,                     -- tiêu đề Điều/Chương nếu có
  text          text NOT NULL,
  parent_id     text,
  ordinal       int NOT NULL,             -- thứ tự trong văn bản
  pdf_page      int                       -- trang PDF tương ứng (nếu khớp được)
);

CREATE TABLE amendments (
  amendment_id      text PRIMARY KEY,
  amending_vbpl_id  bigint NOT NULL,      -- văn bản sửa (vd NĐ 238/2026)
  target_so_hieu    text NOT NULL,        -- văn bản bị sửa (vd 168/2024/NĐ-CP)
  target_key        text NOT NULL,        -- provision_key bị tác động
  action            text NOT NULL,        -- sua_doi | bo_sung | bai_bo | unsupported
  new_text          text,
  effective_date    date NOT NULL,
  raw_instruction   text NOT NULL,        -- câu gốc "Sửa đổi, bổ sung điểm a khoản 4 Điều 18 ..."
  parse_status      text NOT NULL         -- ok | needs_review
);

CREATE TABLE provision_versions (         -- phiên bản HỢP NHẤT theo thời gian
  provision_key   text NOT NULL,
  version_no      int  NOT NULL,
  text            text,                   -- null nếu bị bãi bỏ
  source_vbpl_id  bigint NOT NULL,        -- văn bản tạo ra phiên bản này
  valid_from      date NOT NULL,
  valid_to        date NOT NULL DEFAULT '9999-12-31',  -- [valid_from, valid_to)
  is_current      boolean NOT NULL,
  PRIMARY KEY (provision_key, version_no)
);
```

**Quy tắc dựng `provision_versions`:**
1. Version 1 của mọi điều khoản: text gốc, `valid_from = documents.ngay_hieu_luc` của văn bản gốc.
2. Với mỗi `amendments` có `parse_status = ok`, sắp xếp theo `effective_date`: đóng version hiện tại (`valid_to = effective_date`), mở version mới (`valid_from = effective_date`). `bai_bo` → version mới có `text = NULL`.
3. Nếu văn bản gốc `het_hieu_luc` với `ngay_het_hieu_luc` biết trước: đóng version cuối tại ngày đó.
4. Truy vấn theo thời điểm X: `WHERE valid_from <= X AND X < valid_to`.
5. Chạy lại job → kết quả giống hệt (deterministic, idempotent).

### 6.4. Hành vi vi phạm (bảng phục vụ câu hỏi phụ)
```sql
CREATE TABLE violations (
  violation_id      text PRIMARY KEY,     -- {provision_key}@v{version_no}#{idx}
  provision_key     text NOT NULL,        -- thường là cấp Điểm
  version_no        int NOT NULL,
  hanh_vi           text NOT NULL,        -- mô tả hành vi
  phuong_tien       text[] NOT NULL,      -- {xe_may, o_to, xe_dap, xe_may_chuyen_dung, nguoi_di_bo, ...}
  doi_tuong         text,                 -- ca_nhan | to_chuc
  muc_phat_min      bigint,               -- đồng
  muc_phat_max      bigint,
  tru_diem_gplx     int,
  tuoc_gplx_min_thang int,
  tuoc_gplx_max_thang int,
  bien_phap_bo_sung text[],
  attributes        jsonb NOT NULL DEFAULT '{}',  -- thuộc tính phân biệt, vd {"nong_do_con":"tren_80mg"}, {"vuot_toc_do":"10_20kmh"}
  valid_from        date NOT NULL,
  valid_to          date NOT NULL,
  extraction_method text NOT NULL,        -- regex | llm | manual
  confidence        real,
  needs_review      boolean NOT NULL DEFAULT false
);
```
> Lưu ý cấu trúc nghị định xử phạt: **mức phạt thường nằm ở câu dẫn của Khoản** ("Phạt tiền từ X đồng đến Y đồng đối với người điều khiển xe… thực hiện một trong các hành vi vi phạm sau đây:"), còn **hành vi nằm ở từng Điểm**. Loại phương tiện thường nằm ở **tiêu đề Điều**. Trừ điểm GPLX nằm ở một Khoản riêng cuối Điều, dẫn chiếu ngược lại các điểm. Bộ trích xuất phải kế thừa thông tin từ Điều → Khoản → Điểm.

### 6.5. Chunks cho RAG
```sql
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS unaccent;

CREATE TABLE chunks (
  chunk_id        text PRIMARY KEY,       -- {provision_key}@v{version_no}
  provision_key   text NOT NULL,
  version_no      int NOT NULL,
  vbpl_id         bigint NOT NULL,
  so_hieu         text NOT NULL,
  hierarchy_path  text NOT NULL,          -- "Chương II > Điều 18. Xử phạt ... > Khoản 4 > Điểm a"
  embed_text      text NOT NULL,          -- "[{ten_van_ban}] - [{hierarchy_path}] : {text}"
  display_text    text NOT NULL,
  embedding       vector(1024),
  tsv             tsvector,               -- to_tsvector('simple', unaccent(embed_text))
  valid_from      date NOT NULL,
  valid_to        date NOT NULL
);
CREATE INDEX ON chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX ON chunks USING gin (tsv);
CREATE INDEX ON chunks (valid_from, valid_to);
```

### 6.6. Chất lượng dữ liệu, sự kiện, feedback
```sql
CREATE TABLE quarantine (
  id          bigserial PRIMARY KEY,
  stage       text NOT NULL,              -- crawl | parse | extract | amend
  entity_ref  text NOT NULL,
  rule        text NOT NULL,
  detail      jsonb,
  run_id      uuid,
  resolved    boolean DEFAULT false
);

CREATE TABLE qa_sessions (
  session_id  uuid PRIMARY KEY,
  question    text NOT NULL,
  as_of_date  date NOT NULL,
  slots       jsonb NOT NULL DEFAULT '{}',
  status      text NOT NULL,
  answer      jsonb
);

CREATE TABLE qa_topic_counts (            -- sink của streaming job
  window_start timestamptz NOT NULL,
  window_end   timestamptz NOT NULL,
  topic        text NOT NULL,
  n_questions  int NOT NULL,
  n_thumbs_down int NOT NULL,
  updated_batch_id bigint NOT NULL,
  PRIMARY KEY (window_start, topic)
);
```

---

## 7. Crawler (Ingestion, FDE Ch.7)

### 7.1. File `config/sources/vbpl.yaml` (mẫu, selector là placeholder)
```yaml
selector_version: "2026-10-20.v0"     # tăng khi sửa selector
base_url: "https://vbpl.vn"
detail_url_template: "https://vbpl.vn/van-ban/chi-tiet/{slug}--{vbpl_id}?tabs={tab}"
id_regex: "--(\\d+)(?:\\?|$)"          # lấy vbpl_id từ URL
tabs:
  fulltext: "toan-van"                 # ĐÃ XÁC NHẬN
  attributes: "TODO"                   # xác nhận ở Milestone 1
  related: "TODO"
  original_file: "TODO"
selectors:                              # TODO: viết từ fixtures, không đoán
  so_hieu: "TODO"
  ten_van_ban: "TODO"
  loai_van_ban: "TODO"
  co_quan_ban_hanh: "TODO"
  ngay_ban_hanh: "TODO"
  ngay_hieu_luc: "TODO"
  ngay_het_hieu_luc: "TODO"
  tinh_trang: "TODO"
  fulltext_container: "TODO"
  related_items: "TODO"
  pdf_links: "TODO"
search:
  url_template: "TODO"
  result_item_link: "TODO"
  next_page: "TODO"
date_format: "%d/%m/%Y"
required_fields: [so_hieu, ten_van_ban, ngay_ban_hanh, fulltext_container]
```

### 7.2. Hành vi trình duyệt (`browser.py`)
- Playwright Chromium, **1 context, 1 trang tại một thời điểm** (không song song).
- Rate limit: chờ ngẫu nhiên `min_delay_s..max_delay_s` (mặc định 3–6 giây) giữa các lần tải trang.
- Đọc `robots.txt` lúc khởi động; nếu đường dẫn bị cấm thì dừng và báo.
- User-Agent mặc định của trình duyệt; thêm header liên hệ trong config nếu cần. Không giả mạo danh tính.
- Chờ `fulltext_container` (hoặc selector chính của trang) xuất hiện, timeout 30 giây.
- **Phát hiện bị chặn:** HTTP 403/429, trang không chứa selector chính sau timeout, hoặc nội dung chứa dấu hiệu challenge (định nghĩa danh sách chuỗi trong config). Khi bị chặn:
  1. Ghi `crawl_runs.status = blocked`.
  2. Dừng toàn bộ run (không retry dồn dập).
  3. Lần chạy tiếp theo theo lịch mới thử lại.
- Retry lỗi mạng: tối đa 3 lần, backoff 10s, 30s, 90s. Quá 3 lần → `status = failed`.

### 7.3. Tầng 1: Discover
- **Mode `seed`** (mặc định giai đoạn 1): đọc `config/seed_documents.yaml` (danh sách URL hoặc vbpl_id) → thêm vào `crawl_queue(stage='detail', status='pending')` nếu chưa có.
- **Mode `search`** (giai đoạn 2): mở trang tìm kiếm theo từ khoá/lĩnh vực, duyệt phân trang, lấy link chi tiết, trích `vbpl_id` bằng `id_regex`.
- **Mode `follow_relations`**: sau tầng 2, văn bản liên quan (sửa đổi/hướng dẫn) chưa có trong DB được thêm vào queue, giới hạn độ sâu `max_relation_depth` (mặc định 1).

### 7.4. Tầng 2: Detail
Với mỗi `crawl_queue(stage='detail', status='pending')`:
1. Mở tab toàn văn và các tab metadata/liên quan (theo config).
2. Lưu HTML gốc từng tab vào Bronze (bỏ qua nếu hash trùng bản gần nhất).
3. Trích metadata bằng selector → chuẩn hoá ngày, `tinh_trang_norm`.
4. `schema_check`: đủ `required_fields`, ngày hợp lệ, `so_hieu` khớp regex số hiệu (`^\d+/\d{4}/[A-ZĐ0-9-]+$` sau chuẩn hoá). Lỗi → `quarantine`, `crawl_queue.status = failed`.
5. Upsert `documents`, `document_relations (origin='metadata_tab')`.
6. Nếu `content_hash` khác lần trước → đánh dấu văn bản cần parse lại (`needs_reparse = true` trong metadata JSON).
7. Thêm `crawl_queue(stage='download')` cho các link PDF.

### 7.5. Tầng 3: Download
1. Tải file qua Playwright (`page.expect_download()` hoặc request trong context trình duyệt).
2. Kiểm tra: bắt đầu bằng `%PDF`, size > 1 KB, PyMuPDF mở được. Sai → quarantine.
3. `sha256` → nếu đã có trong `document_files` thì `skipped`; nếu chưa → upload `bronze/pdf/{sha256}.pdf`, insert `document_files`.
4. Xác định `has_text_layer`: tỉ lệ trang có ≥ 50 ký tự text.

### 7.6. Incremental và replay
- Mỗi run chỉ xử lý dòng `pending`/`failed (retry_count < 3)`.
- Job định kỳ (hằng tuần) đánh dấu lại `pending` cho văn bản `con_hieu_luc` để phát hiện thay đổi tình trạng hiệu lực/văn bản liên quan mới.
- Parse lại toàn bộ từ Bronze bằng lệnh `luatgt reparse --all` (không cần crawl lại).

### 7.7. CLI
```
luatgt crawl --mode seed|search|follow_relations [--limit N]
luatgt crawl --save-fixtures tests/fixtures/vbpl/   # Milestone 1: lưu HTML mẫu mọi tab
luatgt reparse --all | --vbpl-id 23289
```

---

## 8. Parsing và Transformation (FDE Ch.8)

### 8.1. Nguồn văn bản cho parser
1. **Ưu tiên HTML toàn văn** (`tabs=toan-van`): ít lỗi hơn PDF.
2. **Fallback PDF** khi không có HTML toàn văn hoặc HTML rỗng; PDF scan → OCR Tesseract `vie`.
3. Luôn cố gắng **khớp Điều với số trang PDF** (tìm chuỗi "Điều {n}." trong text từng trang) để trích dẫn được trang.

### 8.2. Chuẩn hoá (`normalize.py`)
- Unicode NFC; thay ký tự lạ (`\u00a0`, tab) bằng khoảng trắng; gộp khoảng trắng.
- Bỏ header/footer lặp lại (dòng xuất hiện trên ≥ 50% số trang PDF).
- Giữ nguyên chữ "đ" trong số thứ tự điểm.

### 8.3. Tách cấu trúc (`structure.py`)
Regex theo dòng (sau chuẩn hoá), xét theo thứ tự ưu tiên:
```
PHẦN      ^Phần\s+(thứ\s+)?([IVXLC]+|\w+)
CHƯƠNG    ^Chương\s+([IVXLC]+)\b
MỤC       ^Mục\s+(\d+)\b
ĐIỀU      ^Điều\s+(\d+[a-z]?)\.\s*(.*)$
KHOẢN     ^(\d+)\.\s+(.*)$                 # chỉ hợp lệ khi đang ở trong một Điều
ĐIỂM      ^([a-zđ])\)\s+(.*)$              # chỉ hợp lệ khi đang ở trong một Khoản
```
- Dòng không khớp → nối vào node hiện tại.
- Kiểm tra: số Điều tăng liên tục; số Khoản trong mỗi Điều bắt đầu từ 1; điểm theo thứ tự a, b, c, d, đ, e… Vi phạm → quarantine (vẫn lưu, gắn cờ).
- Khi HTML có thẻ/class đánh dấu Điều, dùng chúng thay regex (quyết định sau khi khảo sát fixtures).
- **Đặc biệt với văn bản sửa đổi** (NĐ 238/2026, Luật 118/2025): nội dung mới nằm trong ngoặc kép bên trong một Điều/Khoản của văn bản sửa đổi. Không được tách ngoặc kép đó như Điều/Khoản của chính văn bản sửa đổi; chuyển nguyên khối cho `amendments.py`.

### 8.4. Parse sửa đổi (`amendments.py`)
Nhận diện các mẫu câu (không phân biệt hoa thường, sau chuẩn hoá):
```
Sửa đổi, bổ sung (điểm X )?(khoản Y )?Điều Z (của|tại) <số hiệu văn bản>?
Bổ sung (điểm X vào )?(khoản Y )?(vào )?Điều Z ...
Bãi bỏ (điểm X, )*(khoản Y, )*Điều Z ...
```
- Một câu có thể tác động nhiều mục ("điểm a, điểm b khoản 3"): sinh nhiều bản ghi `amendments`.
- `target_so_hieu`: lấy từ tên văn bản sửa đổi ("sửa đổi, bổ sung một số điều của Nghị định số 168/2024/NĐ-CP") nếu câu không nêu.
- `new_text`: đoạn trong ngoặc kép ngay sau câu chỉ dẫn.
- `effective_date`: ngày hiệu lực của văn bản sửa đổi (hoặc ngày riêng nếu Điều khoản thi hành quy định khác → đánh dấu `needs_review`).
- Mẫu không nhận diện được ("thay cụm từ…", "thay thế…") → `action = unsupported`, `parse_status = needs_review`.

### 8.5. Trích xuất hành vi vi phạm (`violations.py`)
Áp dụng cho các Điều trong chương xử phạt của NĐ 168/2024 (và phiên bản đã hợp nhất).
1. **Ngữ cảnh kế thừa:** `phuong_tien` từ tiêu đề Điều (từ điển ánh xạ cụm từ → mã: "xe ô tô" → `o_to`, "xe mô tô, xe gắn máy" → `xe_may`…); `muc_phat_min/max` từ câu dẫn của Khoản.
2. **Regex số tiền:** `từ\s+([\d\.]+)\s+đồng\s+đến\s+([\d\.]+)\s+đồng` → bỏ dấu chấm → int.
3. **Trừ điểm / tước GPLX:** parse các Khoản "trừ điểm giấy phép lái xe" và "tước quyền sử dụng giấy phép lái xe từ X tháng đến Y tháng" dẫn chiếu các điểm cụ thể → gắn ngược vào violations tương ứng.
4. **Thuộc tính phân biệt (`attributes`):** từ điển regex cho các chiều thường gặp:
   - `nong_do_con`: "chưa vượt quá 50 miligam/100 mililít máu…", "vượt quá 50 … đến 80…", "vượt quá 80…"
   - `vuot_toc_do`: "từ 05 km/h đến dưới 10 km/h", …
   - `gay_tai_nan`: có/không
   - Danh sách chiều và regex đặt trong `config/violation_attributes.yaml`.
5. **LLM (tuỳ chọn) cho trường khó:** gọi LLM với JSON schema cố định; kết quả LLM **phải qua kiểm tra**: số tiền trùng với regex nếu regex tìm được; `phuong_tien` thuộc từ điển; nếu không khớp → `needs_review = true`.
6. Mỗi violation lưu `valid_from/valid_to` lấy từ `provision_versions` tương ứng.

### 8.6. Data quality rules (`quality/checks.py`)
| Rule | Mức | Hành động |
|---|---|---|
| `muc_phat_min <= muc_phat_max` | error | quarantine |
| Mức phạt trong khoảng hợp lý (≥ 50.000 và ≤ 150.000.000 đồng, cấu hình được) | warn | `needs_review` |
| Số Điều liên tục, không trùng | error | quarantine văn bản |
| Mỗi amendment `ok` có `target_key` tồn tại trong `provisions` | error | đổi thành `needs_review` |
| Không có hai version chồng lấn thời gian cho cùng `provision_key` | error | dừng job build_gold |
| `phuong_tien` không rỗng với violations | warn | `needs_review` |

Mỗi run ghi tổng số bản ghi pass/warn/error vào log và `crawl_runs`/bảng metrics. **Không bao giờ bỏ bản ghi lỗi một cách âm thầm.**

### 8.7. Spark jobs
- `jobs/build_silver.py`: đọc Bronze (HTML/PDF/meta) → parse → ghi Parquet Silver (overwrite theo partition `vbpl_id`, idempotent).
- `jobs/build_gold.py`: Silver → `provision_versions`, `violations` → Parquet Gold → upsert Postgres.
- `jobs/build_index.py`: Gold → `chunks` (embed_text, embedding, tsv) → upsert Postgres. Chỉ embed lại chunk có `embed_text` thay đổi (so hash).

---

## 9. Retrieval (FDE Ch.9: Serving)

### 9.1. Chunking
- Đơn vị chunk = **Điểm**; nếu Khoản không có Điểm thì chunk = Khoản; Điều không có Khoản thì chunk = Điều.
- `embed_text = "[{ten_van_ban}] - [{hierarchy_path}] : {câu dẫn của Khoản nếu chunk là Điểm} {text}"`, để mỗi chunk tự đủ nghĩa (có cả mức phạt từ câu dẫn).
- Mỗi version của điều khoản là một chunk riêng, mang `valid_from/valid_to`.

### 9.2. Hybrid search (`search.py`)
Input: `query`, `as_of_date`, `k=20`.
1. **Lọc hiệu lực:** `valid_from <= as_of_date < valid_to` (áp dụng cho cả hai nhánh).
2. **Nhánh keyword:** `ts_rank(tsv, plainto_tsquery('simple', unaccent(query)))`, top 50.
3. **Nhánh vector:** cosine trên `embedding`, top 50.
4. **Gộp bằng Reciprocal Rank Fusion:** `score = Σ 1/(60 + rank_i)`.
5. Trả về top `k` chunk + `provision_key` + violations liên kết.
6. Tuỳ chọn: reranker cross-encoder (bật bằng config).

### 9.3. Phân tích câu hỏi
- Trích sẵn từ câu hỏi các slot dễ nhận diện bằng từ điển: loại xe ("xe máy", "ô tô"), nồng độ cồn, tốc độ, ngày ("hôm 1/8").
- `as_of_date` mặc định = ngày hôm nay (múi giờ Asia/Ho_Chi_Minh), trừ khi người dùng nêu thời điểm vi phạm.

---

## 10. Câu hỏi phụ (Follow-up engine), tính năng trọng tâm

### 10.1. Nguyên tắc
Câu hỏi phụ **sinh từ dữ liệu có cấu trúc** (`violations`), không để LLM tự nghĩ. LLM chỉ được dùng để diễn đạt lại câu hỏi cho tự nhiên (tuỳ chọn).

### 10.2. Thuật toán (`qa/followup.py`)
```
Input: question, as_of_date, slots đã có (từ câu hỏi + các lựa chọn trước)
1. chunks = hybrid_search(question, as_of_date)
2. C = violations liên kết với top chunks, có score retrieval
3. Lọc C theo slots đã có (phuong_tien ∈ ..., attributes khớp ...)
4. Nếu |C| == 0  → status = not_found (gợi ý diễn đạt lại / chọn chủ đề)
5. Nếu |C| == 1  → status = answered
6. Nếu tất cả c ∈ C có cùng (muc_phat_min, muc_phat_max, tru_diem, tuoc_gplx)
                 → status = answered (trả lời chung, liệt kê các hành vi)
7. Ngược lại, với mỗi chiều d ∈ D = {phuong_tien, doi_tuong, các key trong attributes, thoi_diem}:
     - values(d) = các giá trị khác nhau của d trong C (có trọng số = score)
     - gain(d)   = entropy có trọng số của d trên C
                   × (chênh lệch mức phạt tối đa giữa các nhóm giá trị của d / mức phạt lớn nhất)
   Chọn tối đa 2 chiều có gain cao nhất (gain > ngưỡng cấu hình).
8. Sinh câu hỏi cho từng chiều: tiêu đề lấy từ config, options = values(d) đã gắn nhãn tiếng Việt + "Không rõ / bỏ qua"
9. status = need_clarification
10. Giới hạn tối đa 3 vòng hỏi; quá 3 vòng → trả lời dạng bảng các trường hợp còn lại.
```
- Chiều `thoi_diem` chỉ được hỏi khi C chứa violations thuộc **nhiều version khác nhau** của cùng điều khoản (tức là có sửa đổi làm thay đổi kết quả quanh khoảng thời gian liên quan). Option: "Trước {effective_date}" / "Từ {effective_date}".
- "Không rõ" → không lọc theo chiều đó; khi trả lời, liệt kê các trường hợp.

### 10.3. Câu hỏi liên quan (hiển thị dưới câu trả lời)
- 2 câu từ các violations **cùng Điều** (anh em) với câu trả lời.
- 1–2 câu từ thống kê đồng xuất hiện trong `qa_sessions` (người hỏi A thường hỏi tiếp B), khi đủ dữ liệu.
- Mẫu câu sinh theo template, ví dụ: "Mức phạt {hanh_vi} đối với {phuong_tien} là bao nhiêu?"

### 10.4. Cấu hình `config/followup.yaml`
```yaml
max_rounds: 3
max_questions_per_round: 2
gain_threshold: 0.15
dimensions:
  phuong_tien:
    question: "Bạn điều khiển loại phương tiện nào?"
    labels: {xe_may: "Xe máy", o_to: "Ô tô", xe_dap: "Xe đạp", nguoi_di_bo: "Người đi bộ"}
  nong_do_con:
    question: "Nồng độ cồn đo được ở mức nào?"
    labels: {duoi_50mg: "Chưa vượt 50 mg/100 ml máu", "50_80mg": "Từ trên 50 đến 80 mg", tren_80mg: "Trên 80 mg"}
  thoi_diem:
    question: "Vi phạm xảy ra khi nào?"
```

---

## 11. Sinh câu trả lời (`qa/answer.py`)

### 11.1. Hợp đồng đầu ra (JSON, validate bằng Pydantic)
```json
{
  "status": "answered | need_clarification | not_found",
  "answer_markdown": "string",
  "facts": [
    {"hanh_vi": "...", "phuong_tien": ["xe_may"], "muc_phat_min": 0, "muc_phat_max": 0,
     "tru_diem_gplx": 0, "tuoc_gplx": "…", "citation_ids": ["c1"]}
  ],
  "citations": [
    {"id": "c1", "provision_key": "ND168-2024/D18/K4/Pa", "version_no": 2,
     "label": "Điểm a khoản 4 Điều 18 NĐ 168/2024/NĐ-CP (sửa đổi bởi NĐ 238/2026/NĐ-CP)",
     "valid_from": "2026-08-15", "source_url": "https://vbpl.vn/...", "pdf_page": 12}
  ],
  "follow_up_questions": [
    {"dimension": "phuong_tien", "question": "...", "options": [{"value": "xe_may", "label": "Xe máy"}]}
  ],
  "related_questions": ["..."],
  "as_of_date": "2026-10-20",
  "disclaimer": "Thông tin tra cứu, không thay thế tư vấn pháp lý."
}
```

### 11.2. Quy tắc
1. **Số liệu (mức phạt, trừ điểm, tước GPLX) lấy từ bảng `violations`**, không lấy từ LLM. LLM chỉ viết câu văn bao quanh các con số đã có.
2. Prompt chỉ chứa chunks đã truy xuất; yêu cầu LLM chỉ dùng thông tin trong đó, mỗi câu khẳng định phải gắn `citation_id`.
3. **Kiểm tra sau khi sinh:** mọi `citation_id` tồn tại trong danh sách chunks; mọi con số tiền xuất hiện trong `answer_markdown` phải khớp một giá trị trong `facts`. Sai → sinh lại 1 lần; vẫn sai → trả lời dạng template không qua LLM.
4. Không có chunk nào vượt ngưỡng liên quan → `status = not_found`, không đoán.
5. Luôn nêu `as_of_date` và phiên bản văn bản được áp dụng.

---

## 12. API (FastAPI)

| Method | Path | Mô tả |
|---|---|---|
| POST | `/api/ask` | Hỏi lần đầu hoặc trả lời câu hỏi phụ |
| GET | `/api/documents` | Danh sách văn bản (lọc theo tình trạng, loại) |
| GET | `/api/documents/{vbpl_id}` | Metadata + quan hệ + file |
| GET | `/api/provisions/{provision_key}?as_of=YYYY-MM-DD` | Nội dung điều khoản tại thời điểm, kèm lịch sử version |
| POST | `/api/feedback` | 👍/👎 + ghi chú cho một câu trả lời |
| GET | `/api/stats/topics?from=&to=` | Dữ liệu dashboard từ `qa_topic_counts` |
| GET | `/api/health` | Kiểm tra DB, MinIO, model |

**`POST /api/ask` request:**
```json
{"session_id": "uuid | null", "question": "string", "as_of_date": "YYYY-MM-DD | null",
 "selected": {"phuong_tien": "xe_may"}}
```
- `session_id = null` → tạo session mới. Có `session_id` → gộp `selected` vào `slots` và chạy lại thuật toán mục 10.
- Mỗi request ghi một event vào `events/` (mục 13).

---

## 13. Streaming log hành vi (áp dụng P09)

### 13.1. Event schema (JSON, mỗi dòng một event)
```json
{"event_id": "uuid", "event_time": "2026-10-20T07:46:12+07:00", "type": "ask|select_option|feedback",
 "session_id": "uuid", "topic": "nong_do_con", "thumbs": "up|down|null", "client_sent_at": "..."}
```
- `event_time` = lúc người dùng thao tác (lấy từ client). Server thêm `ingest_time`.
- Event có thể đến trễ (mất mạng, gửi lại) và có thể trùng (retry) → đây là dữ liệu at-least-once.

### 13.2. Job `streaming/qa_events_stream.py`
```python
events = (spark.readStream.schema(EVENT_SCHEMA).json("events/")   # hoặc Kafka
          .withWatermark("event_time", cfg.watermark_delay)        # mặc định "10 minutes"
          .dropDuplicatesWithinWatermark(["event_id"]))
counts = (events.groupBy(window("event_time", "10 minutes"), "topic")
          .agg(count(when(col("type") == "ask", 1)).alias("n_questions"),
               count(when(col("thumbs") == "down", 1)).alias("n_thumbs_down")))
(counts.writeStream.outputMode("update")
       .option("checkpointLocation", cfg.checkpoint_dir)
       .foreachBatch(upsert_to_postgres)      # upsert theo (window_start, topic), ghi batch_id
       .start())
```
- `upsert_to_postgres(df, batch_id)`: `INSERT … ON CONFLICT (window_start, topic) DO UPDATE` → sink idempotent, chạy lại cùng batch không làm sai số.
- Log `numRowsDroppedByWatermark` từ `query.lastProgress` vào metrics.
- **Thí nghiệm cho báo cáo:** chạy cùng bộ event (có event trễ cố ý) với 2 watermark (5 phút vs 15 phút), so sánh độ đầy đủ, độ trễ ra kết quả, số event bị drop. Script sinh event giả lập: `eval/gen_events.py`.
- Ghi rõ giới hạn: `foreachBatch` mặc định at-least-once; tính đúng một lần chỉ đạt nhờ upsert idempotent.

### 13.3. Ranh giới thiết kế
Ingestion văn bản luật dùng **batch** (khối lượng nhỏ, cập nhật theo ngày). Streaming chỉ dùng cho log hành vi người dùng. Ghi lý do này trong báo cáo.

---

## 14. Orchestration (Airflow DAGs)

| DAG | Lịch | Task |
|---|---|---|
| `dag_crawl_daily` | 02:00 hằng ngày | `crawl_detail` → `crawl_download` → `follow_relations` |
| `dag_recheck_weekly` | Chủ nhật 03:00 | đánh dấu lại `pending` các văn bản `con_hieu_luc` |
| `dag_build` | sau `dag_crawl_daily` | `build_silver` → `quality_checks` → `build_gold` → `build_index` |
| `dag_eval` | thủ công | `run_eval` → ghi báo cáo vào `eval/reports/` |

- Mọi task idempotent; DAG chạy lại cùng ngày không sinh dữ liệu trùng.
- `quality_checks` fail ở mức error → dừng DAG, không publish Gold mới (Gold cũ vẫn phục vụ).

---

## 15. Frontend (Next.js)

### 15.1. Trang
1. **`/` Hỏi đáp**
   - Ô nhập câu hỏi; chọn "Thời điểm áp dụng" (mặc định hôm nay).
   - Khi `need_clarification`: hiển thị câu hỏi phụ dạng **nút chọn (chips)**, có nút "Không rõ".
   - Khi `answered`: câu trả lời; bảng `facts` (hành vi, phương tiện, mức phạt, trừ điểm, tước GPLX); trích dẫn dạng chip bấm được mở panel bên phải hiển thị nguyên văn điều khoản + link vbpl.vn + số trang PDF; danh sách "Câu hỏi liên quan"; 👍/👎.
   - Disclaimer cố định dưới câu trả lời.
2. **`/van-ban`**: danh sách văn bản, lọc theo tình trạng hiệu lực.
3. **`/van-ban/[id]`**: metadata, quan hệ sửa đổi (dạng danh sách/timeline), cây điều khoản, xem lịch sử version của một điều khoản (so sánh trước/sau).
4. **`/dashboard`**: biểu đồ số câu hỏi theo chủ đề theo cửa sổ 10 phút, tỉ lệ 👎, số bản ghi quarantine theo run.

### 15.2. Yêu cầu
- Responsive (dùng được trên điện thoại).
- Tiếng Việt toàn bộ giao diện.
- Không lưu thông tin định danh người dùng.
- Phong cách thiết kế: **Neo-brutalism** theo design system ở mục 15.3. Mọi màu, viền, bóng, font lấy từ token, không viết giá trị lẻ trong component.

### 15.3. Design system: Neo-brutalism

#### 15.3.1. Nguyên tắc
Neo-brutalism: viền đen dày, bóng đổ cứng (không blur), màu khối mạnh, góc vuông hoặc bo rất ít, chữ đậm, bố cục dạng lưới rõ ràng. Mục tiêu là giao diện **nổi bật, dễ nhận diện, dễ thao tác**.

Vì đây là trang tra cứu luật, áp dụng quy tắc **"khung brutal, nội dung bình tĩnh"**:
- **Phần khung** (header, nút, chip câu hỏi phụ, thẻ, ô nhập, badge, dashboard) dùng đầy đủ phong cách brutal.
- **Phần nội dung pháp lý** (nguyên văn điều khoản, câu trả lời, bảng mức phạt) đặt trong khối nền trắng, chữ cỡ thường, độ đậm thường, line-height rộng, **không** xoay nghiêng, **không** dùng màu nền chói phía sau chữ dài. Như vậy vẫn giữ được cảm giác đáng tin và dễ đọc.
- Không dùng quốc huy, màu cờ, hay bất kỳ yếu tố nào khiến trang bị nhầm là cổng thông tin chính thức của nhà nước.

#### 15.3.2. Màu (CSS variables trên `:root`)
```css
:root {
  --ink:        #111111;   /* viền, chữ chính, bóng đổ */
  --paper:      #FFFDF5;   /* nền trang (trắng ngà) */
  --surface:    #FFFFFF;   /* nền khối nội dung pháp lý */
  --yellow:     #FFD23F;   /* màu nhấn chính: nút chính, highlight */
  --blue:       #3D9BFF;   /* link, chip trích dẫn */
  --pink:       #FF6FB5;   /* câu hỏi phụ (chip lựa chọn) */
  --green:      #4ADE80;   /* trạng thái "còn hiệu lực", 👍 */
  --red:        #FF4D4D;   /* "hết hiệu lực", lỗi, 👎 */
  --orange:     #FF9F43;   /* "hết hiệu lực một phần", cảnh báo, needs_review */
  --muted:      #5A5A5A;   /* chữ phụ */
}
```
- Mọi trạng thái có **chữ hoặc icon kèm theo**, không chỉ dựa vào màu (ví dụ badge "CÒN HIỆU LỰC" có chữ, không chỉ là chấm xanh).
- Chữ đen trên nền vàng/hồng/xanh lá/cam đạt tương phản WCAG AA. Không đặt chữ trắng trên nền vàng hoặc xanh lá.
- Dark mode: **không làm ở giai đoạn 1** (neo-brutalism dựa vào nền sáng + viền đen; dark mode cần thiết kế riêng).

#### 15.3.3. Typography
| Vai trò | Font | Weight | Ghi chú |
|---|---|---|---|
| Heading, nút, badge | **Be Vietnam Pro** | 800–900 | Viết hoa cho badge/nhãn nhỏ |
| Nội dung, câu trả lời, nguyên văn luật | **Be Vietnam Pro** | 400–500 | line-height 1.65 |
| Mã điều khoản, số hiệu, số tiền | **JetBrains Mono** | 500–700 | ví dụ `ND168-2024/D18/K4/Pa` |

- Nạp qua Google Fonts với subset `vietnamese`. **Bắt buộc kiểm tra hiển thị dấu tiếng Việt** (ví dụ "Nghị định", "Điều", "đ)", "ữ", "ỹ") ở mọi weight; font nào lỗi dấu thì thay.
- Cỡ chữ: body 16px (mobile) / 17px (desktop); H1 36–48px; H2 24–28px; nhãn nhỏ 12–13px viết hoa, letter-spacing 0.04em.

#### 15.3.4. Viền, bóng, bo góc, khoảng cách
```css
:root {
  --border:        3px solid var(--ink);
  --border-thin:   2px solid var(--ink);
  --shadow:        5px 5px 0 0 var(--ink);   /* bóng cứng, không blur */
  --shadow-sm:     3px 3px 0 0 var(--ink);
  --shadow-press:  0 0 0 0 var(--ink);
  --radius:        6px;                      /* bo rất ít; 0px cũng được, giữ thống nhất */
  --space:         8px;                      /* lưới 8px: 8, 16, 24, 32, 48 */
}
```

#### 15.3.5. Component
| Component | Mô tả |
|---|---|
| **Button chính** | Nền `--yellow`, `--border`, `--shadow`, chữ 800. Hover: dịch `translate(-2px,-2px)`, bóng 7px. Active/pressed: dịch `translate(5px,5px)`, bóng về 0 (cảm giác "nhấn xuống"). |
| **Button phụ** | Nền `--surface`, cùng viền và bóng. |
| **Ô nhập câu hỏi** | Cao 56–64px, `--border`, `--shadow`, nền trắng, placeholder `--muted`. Focus: viền giữ đen, thêm outline `3px solid var(--blue)` lệch 3px. Nút gửi gắn liền bên phải. |
| **Chip câu hỏi phụ** | Nền `--pink`, `--border-thin`, `--shadow-sm`, chữ 700. Đã chọn: nền `--ink`, chữ trắng. Chip "Không rõ" nền `--surface`. Trên mobile xếp thành hàng cuộn ngang hoặc lưới 2 cột. |
| **Chip trích dẫn** | Nền `--blue`, font mono, ví dụ `[Đ.18 K.4 a) NĐ 168/2024]`; bấm mở panel nguyên văn. |
| **Khối câu trả lời** | Thẻ `--surface`, `--border`, `--shadow`; tiêu đề nhỏ dạng nhãn ("TRẢ LỜI"), nội dung chữ thường. Thanh màu vàng dày 8px ở cạnh trái. |
| **Bảng mức phạt (facts)** | Viền ngoài `--border`, đường kẻ trong `--border-thin`, header nền `--yellow`, số tiền font mono căn phải. Trên mobile chuyển thành danh sách thẻ. |
| **Panel nguyên văn điều khoản** | Desktop: panel trượt bên phải rộng 440px; mobile: bottom sheet. Nền `--surface`, nội dung chữ thường, có: badge hiệu lực, `valid_from–valid_to`, link "Xem trên vbpl.vn", số trang PDF, nút "So sánh phiên bản". |
| **Badge hiệu lực** | `CÒN HIỆU LỰC` (`--green`), `HẾT HIỆU LỰC` (`--red`), `HẾT HIỆU LỰC MỘT PHẦN` (`--orange`), `CHƯA CÓ HIỆU LỰC` (`--surface`). Viền 2px, chữ hoa 800. |
| **So sánh phiên bản** | Hai cột trước/sau; phần bị xoá gạch ngang nền `--red` nhạt, phần thêm nền `--green` nhạt. |
| **Disclaimer** | Hộp viền nét đứt 2px, nền `--paper`, chữ `--muted` 13px, luôn hiện dưới câu trả lời. |
| **Feedback 👍/👎** | Hai nút vuông 44×44px, viền + bóng nhỏ. |
| **Thẻ dashboard** | Mỗi thẻ một màu khối (vàng/xanh/hồng), số liệu lớn font mono 900, nhãn viết hoa. Biểu đồ: nét vẽ đen 2–3px, cột tô màu khối, không gradient. |
| **Trạng thái loading** | Thanh chạy kẻ sọc đen-vàng; nhãn mô tả bước ("Đang tìm điều khoản…", "Đang kiểm tra phiên bản…"). |

#### 15.3.6. Layout từng trang
**Trang `/` (Hỏi đáp)**, bố cục chat:
```
┌──────────────────────────────────────────────────────────┐
│ LUẬTGT ■            [Văn bản] [Dashboard]   [Ngày áp dụng]│  header: viền dưới 3px
├──────────────────────────────────────────────────────────┤
│                                                          │
│   ┌──────────────── câu hỏi người dùng ──────┐ (phải)    │
│                                                          │
│   ┌ TRẢ LỜI ─────────────────────────────────┐ (trái)    │
│   │ Nội dung + chip trích dẫn [Đ.18 K.4 a)]   │           │
│   │ ┌ Bảng mức phạt ───────────────────────┐ │           │
│   │ Disclaimer · 👍 👎                        │           │
│   └───────────────────────────────────────────┘           │
│   CÂU HỎI PHỤ:  [Xe máy] [Ô tô] [Xe đạp] [Không rõ]       │
│   CÂU HỎI LIÊN QUAN: ▸ … ▸ …                             │
│                                                          │
├──────────────────────────────────────────────────────────┤
│ [ Nhập câu hỏi về luật giao thông…            ] [GỬI ▶] │  ô nhập cố định đáy
└──────────────────────────────────────────────────────────┘
                                         panel nguyên văn trượt từ phải →
```
- Màn hình trống ban đầu: tiêu đề lớn + 4–6 thẻ câu hỏi mẫu (mỗi thẻ một màu khối) để người dùng bấm thử.
- Chiều rộng cột chat tối đa 760px, căn giữa.

**Trang `/van-ban`**: lưới thẻ văn bản (2–3 cột desktop, 1 cột mobile). Mỗi thẻ: số hiệu (mono), tên, badge hiệu lực, ngày ban hành/hiệu lực. Thanh lọc phía trên là các chip chọn.

**Trang `/van-ban/[id]`**: cột trái (sticky) là mục lục cây Chương/Điều; cột phải là nội dung. Phía trên có khối metadata và **timeline quan hệ sửa đổi** dạng các khối nối bằng đường kẻ đen dày.

**Trang `/dashboard`**: hàng thẻ số liệu (tổng câu hỏi, tỉ lệ 👎, số bản ghi quarantine, run gần nhất) rồi đến biểu đồ theo cửa sổ thời gian.

#### 15.3.7. Chuyển động
- Chỉ dùng chuyển động ngắn (100–150ms) cho hover/nhấn nút và mở panel.
- Tôn trọng `prefers-reduced-motion`: tắt mọi chuyển động dịch chuyển.
- Không xoay nghiêng, lắc, hay hiệu ứng trang trí trên khối chứa nội dung pháp lý.

#### 15.3.8. Accessibility
- Vùng chạm tối thiểu 44×44px.
- Focus nhìn thấy rõ trên mọi phần tử tương tác (outline xanh 3px).
- Tương phản chữ/nền tối thiểu WCAG AA.
- Chip câu hỏi phụ là `<button>` trong nhóm có `aria-label` là nội dung câu hỏi phụ.

#### 15.3.9. Triển khai (Tailwind)
- Khai báo token trong `web/app/globals.css` (biến CSS ở trên) và ánh xạ vào `tailwind.config.ts` (`colors`, `boxShadow: { brutal: '5px 5px 0 0 #111', 'brutal-sm': '3px 3px 0 0 #111' }`, `borderWidth: { 3: '3px' }`, `fontFamily`).
- Tạo component dùng chung trong `web/components/ui/`: `Button`, `Card`, `Chip`, `Badge`, `Input`, `Table`, `Panel`, `Disclaimer`. Trang chỉ ghép các component này.
- Không dùng thư viện UI có sẵn phong cách riêng (MUI, Ant Design) vì sẽ xung đột với phong cách brutal; có thể dùng Radix UI/shadcn ở dạng headless rồi tự style.

---

## 16. Đánh giá (evidence cho báo cáo)

### 16.1. Bộ câu hỏi `eval/questions.yaml`
```yaml
- id: q001
  question: "Uống rượu bia lái xe máy bị phạt bao nhiêu?"
  as_of_date: "2026-10-20"
  selected: {nong_do_con: tren_80mg}
  expected_provision_keys: ["ND168-2024/D7/K?/P?"]     # nhóm tự điền sau khi có dữ liệu
  expected_fine: {min: 0, max: 0}                       # điền từ văn bản gốc, kiểm tra tay
- id: q050
  question: "<hành vi bị sửa bởi NĐ 238/2026>"
  as_of_date: "2026-08-01"                              # trước hiệu lực sửa đổi
  expected_version_source: "168/2024/NĐ-CP"
```
- Tối thiểu 100 câu; ít nhất 20 câu kiểm tra **đúng phiên bản** (hỏi cùng hành vi trước/sau 15/8/2026).
- Đáp án chuẩn do nhóm đối chiếu tay với văn bản gốc.

### 16.2. Chỉ số
| Chỉ số | Định nghĩa |
|---|---|
| Parse accuracy | % Điều/Khoản/Điểm tách đúng trên 3 văn bản (đối chiếu tay hoặc dataset tham khảo) |
| Extraction accuracy | % violations đúng mức phạt trên mẫu 50 dòng kiểm tra tay |
| Recall@5 | % câu có điều khoản đúng trong top 5 retrieval |
| Citation accuracy | % trích dẫn trỏ đúng điều khoản |
| Version correctness | % câu trả lời dùng đúng phiên bản theo `as_of_date` |
| Avg follow-up rounds | số vòng hỏi phụ trung bình để đến `answered` |

### 16.3. Thí nghiệm so sánh
1. Vector-only vs Hybrid vs Hybrid + bộ lọc hiệu lực.
2. Có câu hỏi phụ vs không có (độ chính xác mức phạt trong câu trả lời).
3. Watermark 5 phút vs 15 phút cho streaming log (mục 13).

---

## 17. Milestones (thứ tự thực hiện cho AI code)

### M0. Khởi tạo dự án
- Repo theo mục 4, `docker-compose.yml` (Postgres+pgvector, MinIO), `pyproject.toml`, config loader, logging.
- Migration tạo toàn bộ bảng mục 6.
- **Nghiệm thu:** `docker compose up` chạy; `pytest` pass test kết nối DB và MinIO.

### M1. Khảo sát nguồn và fixtures (BẮT BUỘC trước khi viết selector)
- `luatgt crawl --save-fixtures`: mở URL mẫu (vbpl_id 23289) và 1 URL của NĐ 168/2024 bằng Playwright, lưu HTML **mọi tab** + chụp màn hình vào `tests/fixtures/vbpl/`.
- Viết `docs/SOURCE_NOTES.md`: tên tab, giá trị `tabs=`, vị trí metadata, cách hiển thị văn bản liên quan, link PDF, cấu trúc HTML toàn văn.
- Điền selector thật vào `config/sources/vbpl.yaml`.
- **Nghiệm thu:** test parse metadata trên fixtures đúng 100% trường bắt buộc; không gọi mạng trong test.

### M2. Crawler 3 tầng
- `browser.py`, `state.py`, `detail.py`, `download.py`, `schema_check.py`, mode `seed`.
- **Nghiệm thu:** chạy seed list → Bronze có HTML + PDF + meta; chạy lại lần 2 không sinh file/bản ghi mới; giả lập bị chặn (mock) → run dừng với `status=blocked`.

### M3. Parsing → Silver
- `normalize.py`, `html_fulltext.py`, `pdf_text.py`, `structure.py`, `build_silver.py`.
- **Nghiệm thu:** NĐ 168/2024 tách đủ các Điều liên tục; test trên fixtures; chạy lại cho cùng output.

### M4. Sửa đổi + phiên bản (SCD2)
- `amendments.py`, `versions.py`.
- **Nghiệm thu:** với NĐ 238/2026, các điều khoản bị sửa có 2 version, không chồng lấn thời gian; truy vấn `as_of=2026-08-01` trả bản cũ, `as_of=2026-10-20` trả bản mới; mẫu không hỗ trợ nằm trong `needs_review`.

### M5. Trích xuất violations + quality
- `violations.py`, `violation_attributes.yaml`, `checks.py`, `build_gold.py`.
- **Nghiệm thu:** kiểm tra tay 50 dòng ngẫu nhiên, ≥ 90% đúng mức phạt; mọi rule mục 8.6 có test.

### M6. Index + retrieval
- `build_index.py`, `embed.py`, `search.py`.
- **Nghiệm thu:** Recall@5 đo được trên ≥ 30 câu eval đầu tiên; bộ lọc hiệu lực có test.

### M7. Follow-up engine + answer + API
- `followup.py`, `answer.py`, `llm_client.py`, routes.
- **Nghiệm thu:** câu "uống rượu lái xe bị phạt bao nhiêu" → `need_clarification` hỏi phương tiện/nồng độ cồn; sau khi chọn → `answered` với mức phạt từ bảng `violations` và trích dẫn hợp lệ; câu không liên quan → `not_found`.

### M8. Frontend
- Design tokens + component dùng chung theo mục 15.3 (làm trước), rồi trang `/`, `/van-ban`, `/van-ban/[id]`.
- **Nghiệm thu:** luồng hỏi → chọn câu hỏi phụ → trả lời → mở trích dẫn chạy được trên điện thoại; toàn bộ màu/viền/bóng lấy từ token; dấu tiếng Việt hiển thị đúng ở mọi font weight; khối nội dung pháp lý giữ nền trắng, chữ thường.

### M9. Streaming + dashboard
- `qa_events_stream.py`, `gen_events.py`, `/dashboard`.
- **Nghiệm thu:** chạy thí nghiệm 2 watermark, xuất bảng so sánh; restart job từ checkpoint không làm sai số liệu.

### M10. Airflow + đánh giá
- DAGs mục 14; `run_eval.py` xuất báo cáo Markdown các chỉ số mục 16.
- **Nghiệm thu:** chạy toàn bộ pipeline từ đầu bằng Airflow; báo cáo eval sinh tự động.

---

## 18. Ánh xạ kiến thức (dùng cho báo cáo và thuyết trình)

| Thành phần hệ thống | Kiến thức áp dụng | Nguồn |
|---|---|---|
| Khảo sát vbpl.vn, schema check, selector có version | Đặc điểm source system, schema evolution, không có data contract | FDE Ch.5 |
| Crawler batch, incremental, retry, idempotent theo hash, replay từ Bronze | Batch vs streaming ingestion, idempotency, late-arriving data, replay | FDE Ch.7; P09 |
| Bronze/Silver/Gold, Parquet, object storage | Kiến trúc lake/lakehouse, định dạng lưu trữ | FDE Ch.3, Ch.6 |
| PDF nhỏ không để trên HDFS | Small-files problem, NameNode metadata trong RAM, block lớn | P01; FDE Ch.6 |
| Spark batch parse/extract | Transformation, distributed processing | FDE Ch.8 |
| `provision_versions` SCD2, truy vấn `as_of` | Data modeling, slowly changing dimension, event time vs processing time | FDE Ch.8; P09 |
| Quality checks + quarantine | Data quality, DataOps, không drop âm thầm | FDE Ch.2 (undercurrents) |
| Hybrid RAG, trích dẫn, câu hỏi phụ | Serving data cho ML/ứng dụng | FDE Ch.9 |
| Streaming log + watermark + checkpoint + upsert sink | Event time, window, watermark, state, output mode, exactly-once có ranh giới | P09; Spark Structured Streaming Guide |
| Airflow | Orchestration | FDE Ch.2 (undercurrents) |
| Rate limit, robots.txt, không lưu PII, disclaimer | Security, privacy, đạo đức dữ liệu | FDE Ch.10 |

> Bổ sung các mã đề khác trong reading list vào bảng này khi đối chiếu.

---

## 19. Rủi ro và giới hạn

| Rủi ro | Giảm thiểu |
|---|---|
| vbpl.vn chặn bot / đổi giao diện | Playwright, rate limit thấp, selector trong config, Bronze để parse lại; dừng khi bị chặn, không vượt rào |
| PDF scan, OCR sai số tiền | Ưu tiên HTML toàn văn; regex kiểm tra chéo; `needs_review` |
| Câu sửa đổi phức tạp không parse được | Chỉ hỗ trợ 3 dạng; còn lại đưa vào hàng đợi xử lý tay |
| LLM bịa số liệu | Số liệu lấy từ bảng; kiểm tra số tiền và trích dẫn sau khi sinh |
| Tình trạng hiệu lực trên trang chưa cập nhật kịp | Job kiểm tra lại hằng tuần; hiển thị ngày crawl gần nhất cạnh câu trả lời |
| Dữ liệu nhỏ, chạy local | Nêu rõ hệ thống minh hoạ cơ chế, không đo hiệu năng production |

---

## 20. Biến môi trường (`.env.example`)
```
POSTGRES_URL=postgresql+psycopg://luatgt:luatgt@localhost:5432/luatgt
MINIO_ENDPOINT=http://localhost:9000
MINIO_ACCESS_KEY=
MINIO_SECRET_KEY=
LLM_PROVIDER=anthropic          # anthropic | openai | local
LLM_MODEL=
LLM_API_KEY=
EMBEDDING_MODEL=BAAI/bge-m3
CRAWL_MIN_DELAY_S=3
CRAWL_MAX_DELAY_S=6
TZ=Asia/Ho_Chi_Minh
```
