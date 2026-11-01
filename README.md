# LuậtGT

Thu thập văn bản luật giao thông từ vbpl.vn, dựng dữ liệu có phiên bản theo thời gian hiệu lực, và hỏi đáp có trích dẫn Điều/Khoản/Điểm.
Thiết kế đầy đủ: [LuatGT_System_Design.md](LuatGT_System_Design.md). Các điểm lệch so với spec: [docs/DECISIONS.md](docs/DECISIONS.md).

## Chạy local

Yêu cầu: Python 3.11+, Docker.

```bash
cp .env.example .env              # máy đã có Postgres ở cổng 5432 thì đổi sang 5433 (xem ghi chú trong file)
docker compose up -d              # Postgres 16 + pgvector, MinIO

python3.11 -m venv .venv
.venv/bin/pip install -e ".[dev]" # thêm extras theo milestone: crawler, parsing, spark, ml, api, hoặc all

.venv/bin/luatgt db migrate       # tạo bảng (chạy lại an toàn)
.venv/bin/luatgt storage init     # tạo bucket bronze/silver/gold nếu chưa có
.venv/bin/luatgt health
.venv/bin/pytest                  # test có đánh dấu `integration` cần docker compose đang chạy
```

Crawler (cần `pip install -e ".[crawler,parsing]"` và `.venv/bin/playwright install chromium`):

```bash
.venv/bin/luatgt crawl --mode seed                                      # crawl seed list: Bronze + Postgres (chạy lại an toàn)
.venv/bin/luatgt crawl --save-fixtures tests/fixtures/vbpl/            # lưu HTML mọi tab của seed có url
.venv/bin/luatgt crawl --save-fixtures tests/fixtures/vbpl/ --url <URL chi tiết>
```
Crawler chạy Chromium có giao diện (vbpl.vn chặn headless, xem docs/DECISIONS.md D-007).

Parse Bronze → Silver bằng Spark (cần `pip install -e ".[parsing,spark]"` và Java 17/21, đặt `JAVA_HOME` trong `.env`):

```bash
.venv/bin/luatgt reparse                     # văn bản có needs_reparse = true
.venv/bin/luatgt reparse --all               # parse lại mọi văn bản trên Bronze (không crawl lại)
.venv/bin/luatgt reparse --vbpl-id 173920
```
Silver nằm ở `data/silver/` và bucket `silver` (gồm cả `amendments` parse từ văn bản sửa đổi).

Silver → Gold (phiên bản điều khoản theo thời gian) và nạp Postgres, rồi tra một điều khoản tại một thời điểm:

```bash
.venv/bin/luatgt build-gold                                             # phiên bản + violations
.venv/bin/luatgt provision 168-2024-ND-CP/D6/K3/Pm --as-of 2026-08-01   # bản gốc NĐ 168
.venv/bin/luatgt provision 168-2024-ND-CP/D6/K3/Pm --as-of 2026-10-20   # bản sửa bởi NĐ 238
```
Văn bản sửa nhiều văn bản (Luật 118, NĐ 184) được xác định đích theo từng Điều; Điều sửa văn bản ngoài seed list bị bỏ qua (D-017). Sửa cụm từ được áp tự động lúc dựng phiên bản (D-018). Mục chưa tự động được (đoạn, phụ lục, ngày hiệu lực riêng cho một phần nội dung) nằm ở bảng `quarantine` (stage `amend`). OCR cho PDF scan cần `tesseract` (`brew install tesseract tesseract-lang`, tuỳ chọn).

Index và tìm kiếm (cần `pip install -e ".[ml]"`; lần đầu tải model `BAAI/bge-m3` khoảng 4,5 GB):

```bash
.venv/bin/luatgt build-index                                            # chỉ embed lại chunk có nội dung đổi
.venv/bin/luatgt search "Xe máy vượt đèn đỏ bị phạt bao nhiêu?" --as-of 2026-10-20
.venv/bin/python eval/run_eval.py                                       # Recall@5, xuất eval/reports/retrieval.md
```

API hỏi đáp (cần `pip install -e ".[api]"`). Không đặt `LLM_API_KEY` thì câu trả lời dạng template:

```bash
.venv/bin/uvicorn --factory luatgt.api.main:app_factory --port 8000
curl -X POST localhost:8000/api/ask -H 'Content-Type: application/json' \
  -d '{"question": "uống rượu lái xe bị phạt bao nhiêu", "as_of_date": "2026-10-20"}'
```

Giao diện web (lần đầu chạy `npm --prefix web ci`), mở http://localhost:3000:

```bash
npm --prefix web run dev
```

MinIO console: http://localhost:9001 (tài khoản lấy từ `MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY`).

## Tiến độ
- [x] M0. Khởi tạo dự án
- [x] M1. Khảo sát nguồn và fixtures (ghi chú: [docs/SOURCE_NOTES.md](docs/SOURCE_NOTES.md))
- [x] M2. Crawler 3 tầng (`luatgt crawl --mode seed`)
- [x] M3. Parsing → Silver (`luatgt reparse --all`)
- [x] M4. Sửa đổi + phiên bản (SCD2) (`luatgt build-gold`, `luatgt provision <key> --as-of <ngày>`)
- [x] M5. Violations + quality (`luatgt build-gold`, mẫu kiểm tra: [docs/M5_SAMPLE_CHECK.md](docs/M5_SAMPLE_CHECK.md))
- [x] M6. Index + retrieval (`luatgt build-index`, `luatgt search`, `eval/run_eval.py`)
- [x] M7. Follow-up engine + answer + API (`uvicorn --factory luatgt.api.main:app_factory`)
- [x] M8. Frontend (`npm --prefix web run dev`, cần API đang chạy; `API_URL` mặc định `http://localhost:8000`)
- [x] M9. Streaming + dashboard (`luatgt stream`, `luatgt stream --once`, `eval/run_watermark_experiment.py`, kết quả: [docs/M9_WATERMARK.md](docs/M9_WATERMARK.md))
- [ ] M10. Airflow + đánh giá
