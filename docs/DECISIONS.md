# Quyết định và điểm lệch so với spec

Ghi theo quy tắc mục 0.8 của `LuatGT_System_Design.md`. Mỗi mục: vấn đề → quyết định → trạng thái.

## D-001. Image Docker của MinIO (M0, 20/10/2026)
- **Vấn đề:** MinIO đã ngừng phát hành image community. `minio/minio` (Docker Hub) và `quay.io/minio/minio` đều không pull được.
- **Quyết định:** dùng `bitnamilegacy/minio:2025.7.23` (vẫn là MinIO, pin phiên bản). Code dùng S3 API qua SDK `minio`, không phụ thuộc image.
- **Hệ quả:** image đã đóng băng, không còn bản vá bảo mật; chỉ phù hợp chạy local. Phương án thay thế nếu cần: `cgr.dev/chainguard/minio` (còn cập nhật, chỉ có tag `latest`) hoặc một server tương thích S3 khác (RustFS, SeaweedFS).
- **Trạng thái:** đã áp dụng.

## D-002. Cột `chunks.tsv` dùng hàm `f_unaccent` IMMUTABLE (M0)
- **Vấn đề:** `unaccent()` của Postgres là STABLE nên không dùng được trong generated column hay index.
- **Quyết định:** tạo hàm `f_unaccent(text)` IMMUTABLE bọc `unaccent('public.unaccent', …)`. `tsv` là generated column `to_tsvector('simple', f_unaccent(embed_text))`. Truy vấn search (M6) dùng `plainto_tsquery('simple', f_unaccent(query))`.
- **Trạng thái:** đã áp dụng.

## D-003. Khoá chính `document_files` = `(sha256, vbpl_id)` (M0)
- **Vấn đề:** spec dùng `sha256` làm khoá chính. Một file PDF đính kèm ở hai văn bản sẽ chỉ gắn được với một văn bản.
- **Quyết định:** khoá chính ghép `(sha256, vbpl_id)`. Object trên Bronze vẫn là một bản duy nhất `bronze/pdf/{sha256}.pdf`.
- **Trạng thái:** đã áp dụng.

## D-004. Cột `documents.needs_reparse` (M0)
- **Vấn đề:** spec 7.4 bước 6 chỉ ghi `needs_reparse` vào JSON metadata trên Bronze, nên `build_silver` khó lọc văn bản cần parse lại.
- **Quyết định:** thêm cột `documents.needs_reparse boolean DEFAULT true`. Crawler bật cột này khi `content_hash` đổi; `build_silver` tắt sau khi parse thành công. JSON metadata vẫn ghi cờ như spec.
- **Trạng thái:** đã áp dụng.

## D-005. Ràng buộc chống chồng lấn version ở tầng DB (M0)
- **Quyết định:** `provision_versions` có `EXCLUDE USING gist (provision_key WITH =, daterange(valid_from, valid_to) WITH &&)` (cần extension `btree_gist`) và `CHECK (valid_from < valid_to)`. Đây là lưới an toàn bổ sung; quality check của `build_gold` (mục 8.6) vẫn là nơi phát hiện và dừng job.
- **Trạng thái:** đã áp dụng.

## D-006. Bổ sung khác (M0)
- Mọi bảng có `created_at`, `updated_at` và trigger tự cập nhật `updated_at` (đúng yêu cầu mục 6).
- CHECK constraint cho các cột trạng thái có tập giá trị liệt kê trong spec.
- `provisions.level` thêm giá trị `phan` vì regex mục 8.3 có cấp "Phần".
- Thêm bảng `schema_migrations` để `luatgt db migrate` chạy lại an toàn.

## D-007. vbpl.vn chặn Playwright headless ngay request đầu tiên (M1, 23/10/2026) — ĐÃ QUYẾT ĐỊNH
- **Vấn đề:** cả `/robots.txt` và trang chi tiết đều trả 403 "Sorry, you have been blocked" (chi tiết trong SOURCE_NOTES.md). Giả định ở spec mục 2.1 ("dùng Playwright Chromium là vào được") không đúng với cấu hình hiện tại.
- **Đã làm:** dừng sau 2 request; không đổi User-Agent, không dùng proxy, không thử lại.
- **Phương án (chọn một):**
  1. Nhóm mở vbpl.vn bằng trình duyệt thường. Nếu vẫn bị chặn thì đây là chặn theo IP/mạng; thử mạng khác (mạng trường) hoặc liên hệ đơn vị quản lý vbpl.vn xin phép.
  2. Chạy Playwright ở chế độ có giao diện (headed), tức Chromium bình thường không sửa định danh. Chỉ dùng nếu nhóm xác nhận cách này không trái quy tắc 3.
  3. Lưu fixtures thủ công: mở trang bằng trình duyệt thường, "Lưu trang" (HTML đầy đủ) vào `tests/fixtures/vbpl/`. Viết selector và parser từ fixtures (M1 vẫn nghiệm thu được). Crawler tự động để sau.
- **Kiểm tra thêm:** trình duyệt thường trên cùng máy, cùng mạng vào được → trang chặn trình duyệt tự động, không chặn IP.
- **Quyết định (23/10/2026, nhóm chọn):** phương án 2. Playwright Chromium ở chế độ headed; không đổi User-Agent, không proxy, không giải CAPTCHA; giữ rate limit 3–6 giây và mỗi lần một trang. Nếu headed vẫn bị chặn thì dừng và chuyển sang phương án 3. Cấu hình: `crawler.headless` trong `config/settings.yaml`.
- **Kết quả:** headed vào được (mọi trang 200).
- **Hệ quả cho M10:** headed cần màn hình. Chạy trong Docker/Airflow phải có màn hình ảo (Xvfb, `xvfb-run`), hoặc chạy crawler trên máy có giao diện.
- **Trạng thái:** đã quyết định.

## D-008. `vbpl_id` có thể là UUID, không chỉ số nguyên (M1, 23/10/2026) — ĐÃ ÁP DỤNG
- **Quyết định (nhóm đồng ý 23/10/2026):** migration `0002_vbpl_id_text.sql` đổi 9 cột `vbpl_id`/`*_vbpl_id` sang `text`, thêm CHECK định dạng (số nguyên hoặc UUID) trên `documents.vbpl_id`.
- **Vấn đề:** NĐ 238/2026 có URL `…--f4b0c320-79e6-11f1-8c8a-3587e086d762`. Spec mục 2.1 và mục 6 coi `vbpl_id` là số nguyên, dùng `bigint` làm khoá ở `documents`, `crawl_queue`, `document_files`, `document_relations`, `provisions`, `amendments`, `provision_versions.source_vbpl_id`, `chunks`. Không thể lưu NĐ 238 với schema hiện tại.
- **Đã làm (không đổi schema):** `id_regex` nhận cả số và UUID; code crawler coi `vbpl_id` là chuỗi; fixtures đặt tên theo chuỗi ID.
- **Đề xuất:** migration `0002` đổi mọi cột `vbpl_id`/`*_vbpl_id` sang `text` (DB đang rỗng nên không mất dữ liệu). `provision_id = {vbpl_id}:{path}` vẫn dùng được. Phương án khác: khoá nội bộ `doc_id bigserial` + cột `vbpl_id text UNIQUE`, nhưng phải đổi nhiều chỗ trong spec hơn.

## D-009. Ánh xạ nhóm "Lược đồ" và trạng thái "Lịch sử" sang `relation_type` (M1) — ĐÃ QUYẾT ĐỊNH
- **Quyết định (nhóm đồng ý 24/10/2026):** giữ ánh xạ hiện tại; thêm loại `can_cu` cho nhóm "Căn cứ ban hành" (migration `0003_relation_can_cu.sql`).
- Ánh xạ nằm ở `relation_groups` / `history_status` trong `config/sources/vbpl.yaml`. Điểm chưa chắc chắn:
  - "Văn bản bị tác động hiệu lực một phần" → `sua_doi` (có thể gồm cả bãi bỏ một phần).
  - "… toàn bộ" → `thay_the` / `bi_thay_the` (có thể là bãi bỏ, `bai_bo`).
  - "Căn cứ ban hành", "dẫn chiếu", "áp dụng", "đính chính", "hợp nhất"… không lưu vì ngoài tập `relation_type` của spec. "Căn cứ ban hành" có ích (NĐ 168 căn cứ Luật 36/2024): đề xuất bổ sung `can_cu` nếu nhóm đồng ý.
- Quan hệ từ tab Lịch sử có `dst_vbpl_id` và ngày hiệu lực; quan hệ từ Lược đồ chỉ có số hiệu. Khi gộp, ưu tiên bản có ID. Cả hai đều `origin = metadata_tab`.

## D-010. File gốc không phải lúc nào cũng là PDF (M1) — ĐÃ QUYẾT ĐỊNH
- **Quyết định (nhóm đồng ý 24/10/2026):** phương án A, chỉ tải PDF. Văn bản không có PDF (vd NĐ 168) thì trích dẫn không có số trang; Điều/Khoản/Điểm vẫn đủ.
- NĐ 168/2024 chỉ có file `.doc`; Luật 26/2001 không có file nào; NĐ 238 có `.doc` và `.pdf` (6 MB).
- File tải bằng nút bấm, không có link trực tiếp.
- **Đề xuất cho M2:** tầng download tải mọi file trong tab Tải về; PDF đi qua kiểm tra `%PDF` như spec 7.5; `.doc`/`.docx` lưu Bronze `bronze/file/{sha256}.{ext}` và ghi `document_files.file_type` = `doc`/`docx` (cần mở rộng CHECK constraint). Parser vẫn ưu tiên HTML toàn văn (spec 8.1); `.doc` chỉ dự phòng (cần LibreOffice/antiword để đọc). Số trang PDF cho trích dẫn chỉ có ở văn bản có PDF.

- **Đang áp dụng (M2):** làm đúng spec 7.5, chỉ tải `.pdf` (`download_extensions: [pdf]` trong vbpl.yaml); file khác được ghi log `download_ignored`. Văn bản không có PDF thì không vào hàng đợi download. Mở rộng sang `.doc` chỉ cần sửa config + CHECK `file_type` khi nhóm đồng ý.

## D-011. Seed list thiếu NĐ 336/2025/NĐ-CP (M1) — ĐÃ KIỂM TRA, CHỜ NHÓM CHỌN
- **Quyết định (24/10/2026):** crawl NĐ 336/2025, xem nội dung rồi nhóm quyết định có đưa vào seed list hay không.
- **Kết quả kiểm tra (fixtures `185666__*.html`):** NĐ 336/2025/NĐ-CP "quy định xử phạt vi phạm hành chính trong hoạt động đường bộ", ban hành 22/12/2025, hiệu lực 01/03/2026, ID `185666`. Toàn văn chỉ nhắc NĐ 168 **một lần**, ở tên Điều 25: "Bãi bỏ một số điều, khoản, điểm của **Nghị định số 100/2019/NĐ-CP** … được sửa đổi, bổ sung bởi … Nghị định số 168/2024/NĐ-CP". Các mục bị bãi bỏ là Điều 12, 13, 14, 15, 23, 24, 28, 31, 74, 80 **của NĐ 100/2019**, không phải của NĐ 168.
- **Kết luận:** NĐ 336 không làm đổi nội dung điều khoản nào của NĐ 168 → bảng phiên bản NĐ 168 (M4) không thiếu mốc. Quan hệ "hết hiệu lực một phần" trên vbpl.vn là liên kết gián tiếp qua NĐ 100.
- **Còn lại cho nhóm chọn:** NĐ 336 là nghị định xử phạt *riêng* cho hoạt động đường bộ (hướng dẫn Luật Đường bộ 35/2024, vốn có trong seed list). Thêm vào seed list nếu muốn hệ thống trả lời cả các vi phạm thuộc lĩnh vực này; không thêm cũng không ảnh hưởng độ đúng của NĐ 168.
- Tab Lược đồ của NĐ 168/2024 ghi **hai** văn bản làm hết hiệu lực một phần: NĐ 238/2026 và NĐ 336/2025/NĐ-CP. Tab Lịch sử chỉ ghi NĐ 238. Nếu NĐ 336/2025 sửa NĐ 168 thì bảng phiên bản (M4) sẽ thiếu một mốc → đề xuất thêm vào seed list sau khi nhóm kiểm tra nội dung.
- NĐ 168 cũng tác động một phần lên NĐ 100/2019/NĐ-CP (văn bản cũ, ngoài phạm vi giai đoạn 1).

## D-012. Hash chống trùng Bronze tính trên panel đã chuẩn hoá, không trên cả trang (M2)
- **Vấn đề:** HTML cả trang đổi mỗi lần tải (lượt xem, build id), nên hash cả trang làm mỗi lần crawl lại đều sinh file Bronze mới, trái tiêu chí nghiệm thu M2. Riêng tab Lược đồ còn trả danh sách theo thứ tự ngẫu nhiên.
- **Quyết định:** Bronze vẫn lưu **nguyên trang** (để replay). Hash trong tên file và `crawl_queue.content_hash` tính trên panel của tab (`tab_panel`), sắp xếp `<li>` với tab trong `hash_unordered_list_tabs`. `content_hash` của văn bản = sha256 của các hash tab.
- **Tên file:** `html/{vbpl_id}/{tab}/{crawled_at}__{sha_panel}.html`; `meta/{vbpl_id}/{crawled_at}__{content_hash[:16]}.json`. Spec ghi `meta/{vbpl_id}/{crawled_at}.json`; thêm hash vì hai lần crawl trong cùng một giây sẽ trùng tên và bản sau bị bỏ (Bronze không ghi đè).
- **Kiểm chứng trên trang thật (23/10/2026):** crawl lại 23289 sau khi sửa → `changed=False`, không ghi file mới. Bronze còn 2 file dư từ trước khi sửa (giữ nguyên theo quy tắc không xoá Bronze).

## D-013. Khoá điều khoản và mở rộng bộ tách cấu trúc (M3)
- **Khoá văn bản trong `provision_key`:** spec 6.3 vừa ghi quy tắc "bỏ dấu, thay `/` bằng `-`" vừa đưa ví dụ `ND168-2024`, hai cái mâu thuẫn. Chọn **quy tắc**: `168/2024/NĐ-CP` → `168-2024-ND-CP`, nên khoá là `168-2024-ND-CP/D18/K4/Pa`. Lý do: không trùng giữa loại văn bản (Luật và Nghị quyết cùng hậu tố `QH15`), áp dụng được cho mọi số hiệu. `eval/questions.yaml` dùng định dạng này.
- **Cấp trên Điều:** Phần `…/PH{số}`, Chương `…/C{số La Mã}` (giữ như văn bản, vd `CII`), Mục `…/C{…}/M{n}` (Mục đánh số lại theo Chương). Khoá Điều **không** kèm Chương/Mục vì Điều đánh số liên tục cả văn bản.
- **Mở rộng regex spec 8.3:** Khoản/Điều có hậu tố chữ (`1a.`, `Điều 4a.`) do văn bản sửa đổi bổ sung; Điểm được nằm thẳng dưới Điều khi Điều không có Khoản; dòng "Phần thứ …" chỉ khớp tiêu đề, không khớp câu thường ("Phần đường xe chạy là…").
- **Văn bản sửa đổi:** nội dung trong ngoặc kép (kể cả nhiều dòng) và dòng nội dung **thiếu** ngoặc kép ngay sau câu "Sửa đổi/Bổ sung … như sau:" (NĐ 238 Điều 8 khoản 3) được giữ nguyên khối trong node chỉ dẫn, cờ `has_quoted_content`, để M4 xử lý.
- **Phần đuôi văn bản** (Nơi nhận, TM./KT., "Luật này đã được Quốc hội … thông qua") tách riêng (`trailer`), không dính vào Điều cuối.
- **Lỗi gõ d/đ trên vbpl.vn:** NĐ 168 Điều 16 k2, Điều 39 k9, Điều 40 k3 có "c) đ) đ)". Chỉ sửa khi vị trí mong đợi là chữ còn lại của cặp d/đ (đã đối chiếu: Điều 16 khoản 4 dẫn chiếu cả "điểm d" và "điểm đ khoản 2"). Giữ `number_raw`, ghi quarantine `diem_relabeled`. Lỗi khác không tự sửa: khoá trùng thêm hậu tố `~2` và ghi `duplicate_key`.
- **Chú thích của vbpl.vn** trong toàn văn (NĐ 168: 45 "sửa đổi, bổ sung", 3 "bổ sung", 3 "bãi bỏ") bị bỏ phần giao diện, đoạn gốc giữ nguyên; nhãn lưu ở `provisions.vbpl_annotations` để kiểm chứng parse sửa đổi ở M4.

## D-014. Spark ghi Silver qua thư mục staging rồi đồng bộ lên MinIO (M3)
- **Vấn đề:** Spark đọc/ghi MinIO trực tiếp cần `hadoop-aws` + AWS SDK bundle (khoảng 500 MB tải từ Maven khi chạy lần đầu).
- **Quyết định:** driver đọc Bronze bằng client MinIO; Spark parse phân tán theo văn bản (`mapPartitions`), ghi Parquet phân vùng `vbpl_id` vào `data/silver/` (ghi đè đúng các partition đã parse), sau đó đồng bộ các partition đó lên bucket `silver` (xoá prefix cũ, upload file mới). Silver tái tạo được từ Bronze nên được phép ghi đè.
- Cột phân vùng `vbpl_id` có cả số và UUID → tắt `partitionColumnTypeInference` để Spark không đoán thành số nguyên.
- Bảng Silver: `documents`, `document_relations`, `provisions`, `parse_issues`. `document_files` vẫn ở Postgres (crawler ghi); `amendments` thêm ở M4.
- **Đường nâng cấp:** muốn đọc/ghi `s3a://` trực tiếp thì thêm `spark.jars.packages=org.apache.hadoop:hadoop-aws:<bản Hadoop của Spark>`; logic parse không đổi.

## D-015. Parse sửa đổi và dựng phiên bản (M4)
- **Phạm vi hỗ trợ (đúng spec 8.4):** sửa đổi/bổ sung/bãi bỏ ở mức Điều, Khoản, Điểm, kể cả "bổ sung … vào trước/sau …", nhiều mục trong một câu ("điểm l, điểm m"), điểm có hậu tố số ("k1"), câu ngữ cảnh nhiều tầng ("… một số điểm, khoản của Điều 20" → "… một số điểm của khoản 5" → "điểm đ"). Mọi câu sửa **cụm từ**, **đoạn**, **thay thế** → `unsupported` + `needs_review` (NĐ 238: 51 mục, gồm 16 chỉ dẫn ở Điều 19 và câu "đoạn thứ hai điểm a khoản 3 Điều 50").
- **Hệ quả cần biết:** phiên bản của các mục trong hàng đợi xử lý tay vẫn là chữ cũ sau 15/08/2026. Đã kiểm tra: không câu nào trong 51 mục chứa số tiền (29 "thay thế cụm từ", 16 "bổ sung cụm từ", 5 "bỏ cụm từ", 1 "đoạn"). Nhưng một số câu **mở rộng hành vi bị phạt**, vd thêm "hoặc chuyển làn đường không bảo đảm khoảng cách an toàn…" (điểm a khoản 2, điểm g khoản 5 Điều 6; điểm e khoản 1 Điều 7; điểm h khoản 6 Điều 8), "hoặc dải dừng xe khẩn cấp", ", xe vận tải nội bộ". Câu hỏi về các hành vi mới này sẽ trả lời thiếu cho tới khi xử lý. Ba mẫu "Bổ sung cụm từ X vào sau/trước cụm từ Y", "Thay thế cụm từ X bằng cụm từ Y", "Bỏ cụm từ X" có cấu trúc rõ, có thể tự động hoá nếu nhóm muốn (ngoài phạm vi giai đoạn 1 theo spec 1.4).
- **Thay cả Điều/Khoản** (vd "Sửa đổi, bổ sung Điều 42"): mọi mục con trong nội dung mới thành bản ghi (`origin = content_child`); mục con cũ không còn trong nội dung mới → `bai_bo` ngầm định (`origin = implied_by_replace`). Silver `amendments` có thêm `origin`, `review_reason`, `level`, `title`; Postgres giữ đúng cột của spec.
- **Quality rule 8.6 trong lúc parse:** sửa mục không tồn tại → `needs_review`; bổ sung mục đã tồn tại hoặc thiếu mục cha → `needs_review`; Điều "Hiệu lực thi hành" nêu thêm ngày riêng → mọi bản ghi của văn bản đó `needs_review`.
- **Phiên bản:** chỉ Điều/Khoản/Điểm. Text của Điều là phần dẫn (tiêu đề Điều không có phiên bản). `is_current = (valid_to = 9999-12-31)` để kết quả không phụ thuộc ngày chạy (spec 6.3 bước 5). Cùng một ngày có nhiều sửa đổi cho một mục → giữ bản sau cùng, ghi cảnh báo.
- **Gold dựng sớm ở M4:** `jobs/build_gold.py` (spec giao cho M5) đã làm phần `provision_versions` và nạp Postgres (`provisions`, `amendments`, `provision_versions`) trong một transaction, để truy vấn `as_of` bằng SQL. M5 thêm `violations` vào cùng job. Lỗi mức error (chồng lấn thời gian) → dừng, không ghi gì, Gold cũ vẫn phục vụ.
- **Nhãn chú thích của vbpl.vn chỉ tin được một phần:** khớp hoàn toàn từ Điều 3 đến hết Điều 20 (kể cả 3 nhãn "được bổ sung" là mốc chèn khoản 1a, 8a, điểm n). Từ Điều 21 nhãn bị lệch (vd NĐ 238 bãi bỏ điểm d, đ, e, g khoản 17 Điều 32 nhưng trang gắn nhãn vào a, b, e, g; còn gắn "bãi bỏ" cho cả Điều 21). Test chỉ đối chiếu đoạn khớp.
- **Kết quả trên dữ liệu thật (27/10/2026):** 186 amendments (31 sửa đổi, 14 bổ sung, 4 bãi bỏ tường minh + mục con/ngầm định; 51 chờ xử lý tay), 2.033 phiên bản, 106 điều khoản có 2 phiên bản, 0 lỗi chất lượng.

## D-016. Hoàn thiện seed list; văn bản sửa nhiều văn bản chưa được parse sửa đổi (M2–M4, 31/10/2026) — ĐÃ XỬ LÝ Ở D-017
- **Đã làm:** thêm 5 văn bản vào seed list, crawl thành công, `reparse` + `build-gold` chạy xong. Số Điều liên tục đủ: Luật 36 (89), Luật 35 (86), Luật 118 (11), NĐ 151 (39), NĐ 184 (28). Gold: 4.682 phiên bản.
- **ID:** 36/2024 `170620`, 35/2024 `172475`, 118/2025 `185923`, 151/2024 `174961`, 184/2025 `0f5e2bd0-d42e-11f1-b226-3fc90cc27485`. Trang chấp nhận slug bất kỳ; `id_regex` cần dạng `slug--id`, nên slug của 151, 184, 35, 36 trong seed là slug rút gọn. Seed list chỉ dùng URL đã mở kiểm tra.
- **Vấn đề 1:** spec coi Luật 118 và NĐ 184 là văn bản sửa đổi một văn bản, nhưng thực tế là văn bản sửa **nhiều** văn bản: Luật 118 sửa 10 luật (Điều 7 sửa Luật 36, Điều 8 sửa Luật 35); NĐ 184 sửa nhiều nghị định (Điều 27 sửa NĐ 151). `is_amending_document` lấy văn bản đích từ tên văn bản, tên hai văn bản này không có số hiệu đích, nên **không sinh amendment nào** (vẫn 186, toàn bộ từ NĐ 238).
- **Hệ quả (trước D-017):** Luật 36, Luật 35 và NĐ 151 chỉ có một phiên bản (bản gốc). Tra ngày sau 01/07/2026 của Luật 36/35 hoặc sau 01/07/2025 của NĐ 151 trả **chữ cũ** cho mục đã bị sửa, không có cảnh báo.
- **Vấn đề 2:** NĐ 236/2026/NĐ-CP (ID `224b21d0-7d9e-11f1-bb7a-69f7cf2f90db`, HL 01/07/2026) sửa NĐ 151 nhưng không có trong seed list spec 1.3. Chưa thêm, chờ nhóm quyết định.
- **Lưu ý thời hạn:** vbpl.vn ghi NĐ 184 hết hiệu lực 01/03/2027 (trong khi tình trạng vẫn "Còn hiệu lực").
- **Đề xuất:** xác định văn bản đích theo từng Điều (tên Điều "Sửa đổi, bổ sung một số điều của <văn bản>"), parse trong phạm vi Điều đó, và thêm NĐ 236 vào seed list. Luật dẫn chiếu theo tên (không có số hiệu) cần bảng ánh xạ tên → số hiệu.
- **Môi trường:** `~/.zshrc` đặt `PYSPARK_PYTHON` sang virtualenv khác (Python 3.13) khiến Spark lỗi `PYTHON_VERSION_MISMATCH`. `get_spark` nay luôn dùng Python của tiến trình đang chạy.
- **Tra ID:** kết quả tìm kiếm trên `/van-ban/trung-uong` chứa `document_url` dạng `/van-ban/chi-tiet/{id}`. Tra thủ công bằng trình duyệt, không có mode `search` tự động.

## D-017. Xác định văn bản đích theo từng Điều; thêm NĐ 236 (M4, 31/10/2026) — ĐÃ ÁP DỤNG
- **Quyết định (nhóm đồng ý 31/10/2026):** sửa parser theo đề xuất D-016 và thêm NĐ 236/2026/NĐ-CP vào seed list (ngoài spec 1.3).
- **Văn bản đích:** văn bản có "sửa đổi"/"bãi bỏ" trong tên đều được parse. Đích lấy theo số hiệu ở tiêu đề Điều, hoặc theo tên luật khớp đúng với tên văn bản trong seed list ("… của Luật Đường bộ"). Điều sửa văn bản ngoài seed list thì bỏ qua (8 luật của Luật 118, các nghị định khác của NĐ 184). Câu nêu văn bản khác ngay trong chỉ dẫn đi theo văn bản đó (NĐ 236 bãi bỏ khoản 3, 4 Điều 27 **của NĐ 184**, không phải của NĐ 151).
- **Sửa đổi nối tiếp:** `compute_amendments` chạy theo thứ tự ngày hiệu lực và cập nhật danh sách mục sau mỗi văn bản, để NĐ 236 sửa được mục NĐ 184 đã đổi.
- **Lệch spec 8.4 (ngày hiệu lực riêng):** spec cho mọi bản ghi `needs_review`. Áp dụng theo từng mục: "Quy định tại <mục> … có hiệu lực từ ngày X" → mục đó dùng ngày X (Luật 118, điểm a khoản 20 Điều 7: 01/01/2026); "Quy định <mô tả> tại <mục> …" chỉ là một phần nội dung → riêng mục đó `needs_review`; câu không xác định được mục → vẫn mọi bản ghi `needs_review` như spec. Câu "hết hiệu lực" không tính. Điều "Điều khoản thi hành" cũng được đọc (trước đây bỏ sót).
- **Sửa thêm:** câu trộn "sửa đổi khoản 18 và bổ sung khoản 18a" tách hành động theo từng mục; bãi bỏ Điều/Khoản kéo theo mục con (`implied_by_replace`); "Sửa đổi tên Điều" → `unsupported` (tiêu đề Điều không có phiên bản).
- **Kết quả trên dữ liệu thật:** 446 amendments, 4.931 phiên bản, 271 điều khoản nhiều phiên bản, 0 lỗi chất lượng, 0 cặp chồng lấn. NĐ 238 → NĐ 168 không đổi (186 amendments, 106 điều khoản). Đã đối chiếu mẫu ở Luật 36, Luật 35, NĐ 151, NĐ 184.
- **Hàng đợi xử lý tay còn 117 mục:** 103 cụm từ/đoạn/thay thế (51 của NĐ 238; 52 của Luật 118, NĐ 184, NĐ 236, phần lớn đổi tên cơ quan như "Bộ Giao thông vận tải" → "Bộ Xây dựng") và 14 mục của NĐ 236 có ngày riêng 01/07/2027 cho một phần nội dung (điểm a–d khoản 3 Điều 10 và Điều 25a mới của NĐ 151). Điều 25a vì vậy chưa có trong bảng phiên bản; khoản 3 Điều 10 còn chữ của NĐ 184.
- **Giới hạn còn lại:** thay Phụ lục (NĐ 236 Điều 16) chưa xử lý vì Phụ lục không có trong `provisions`. Điều luật gốc có ngày hiệu lực riêng (Luật 36 Điều 88 khoản 2, khoản 3 Điều 10) vẫn tính từ ngày hiệu lực chung của luật.
- **Văn bản khác chưa có trong seed list:** vbpl.vn còn ghi NĐ 319/2026/NĐ-CP tác động NĐ 151 (hiệu lực 01/07/2027) và Luật 143/2025/QH15 tác động Luật 35. Nhãn "Văn bản bị bãi bỏ một phần" của Luật 35 chưa có trong `relation_groups`.
- **Test:** quy tắc mới có unit test dữ liệu giả; chưa có fixtures cho Luật 118, NĐ 184, NĐ 236 nên kết quả thật mới kiểm tra qua pipeline.

## D-018. Tự động hoá sửa cụm từ (M4, 31/10/2026) — ĐÃ ÁP DỤNG
- **Quyết định (nhóm đồng ý 31/10/2026):** làm ba mẫu "Bổ sung cụm từ", "Thay thế cụm từ", "Bỏ/Bãi bỏ cụm từ", vốn ngoài phạm vi giai đoạn 1 ở spec 1.4. Thay cho nhận định "chờ xử lý tay" ở D-015 và D-017.
- **Cách làm:** `parse_phrase_edits` tách câu thành thao tác và nơi áp dụng, kể cả câu nhiều vế ("Bỏ cụm từ A tại X, cụm từ B tại Y"). Bản ghi có `origin = phrase`, `action = sua_doi`, các cột `phrase_op`, `phrase_old`, `phrase_scope` ở Silver. Text mới tính lúc dựng phiên bản (`_apply_phrases`) vì phụ thuộc text đang có hiệu lực tại ngày đó.
- **Phạm vi áp dụng:** mục được nêu và các mục con ("tại khoản 5 Điều 42" có thể nằm ở điểm con). "tại tên khoản" chỉ áp dòng tên của khoản.
- **Khớp cụm:** phân biệt hoa thường, nguyên từ ("khoản 2" không khớp "khoản 20"). Thay thế và bỏ áp mọi lần xuất hiện. Chèn cần đúng một lần khớp trong mỗi mục; nhiều hơn → `phrase_ambiguous`. Không khớp ở đâu → `phrase_not_found`. Hai trường hợp này giữ nguyên text và ghi `quarantine`.
- **Thứ tự cùng văn bản:** chèn trước, rồi cụm dài trước cụm ngắn. NĐ 238 vừa "Thay thế giấy chứng nhận kiểm định" vừa "Bỏ giấy chứng nhận kiểm định an toàn kỹ thuật…" ở cùng mục.
- **Giữ nguyên chữ theo chỉ dẫn:** không tự sửa câu cho "đẹp". NĐ 236 viết "bổ sung cụm từ “xe vận tải nội bộ”" không có dấu phẩy, nên khoản 4 Điều 1 và Điều 27 NĐ 151 đọc thành "xe ô tô kinh doanh vận tải xe vận tải nội bộ"; NĐ 238 bỏ cụm ở điểm b khoản 7 Điều 32 NĐ 168 để lại "; theo quy định". Đây là thay đổi của máy theo đúng chữ, không phải văn bản hợp nhất chính thức.
- **Kết quả trên dữ liệu thật:** 449 amendments, 5.032 phiên bản, 366 điều khoản nhiều phiên bản, 0 chồng lấn, 0 `phrase_not_found`, 0 `phrase_ambiguous`. Đã đọc từng chỗ đổi của các câu bỏ và chèn; câu thay thế chỉ kiểm tra bằng số khớp.
- **Hàng đợi xử lý tay còn 19 mục:** 14 mục NĐ 236 có ngày riêng 01/07/2027 (D-017), "đoạn thứ hai điểm a khoản 3 Điều 50" của NĐ 238, 4 Phụ lục của NĐ 236.

## D-019. Trích xuất violations và quality rules (M5, 31/10/2026)
- **Thời gian:** mỗi mốc phiên bản dựng lại cả Điều rồi gộp lát giống nhau, vì câu dẫn Khoản, Điểm và Khoản trừ điểm có thể đổi độc lập. `valid_from/valid_to` có thể hẹp hơn phiên bản của chính Điểm. `violation_id` vẫn là `{provision_key}@v{version_no}#{idx}`.
- **Khoá của dòng:** thường là Điểm. Khoản không có Điểm thì khoá là Khoản. Câu dẫn hai mức (cá nhân, tổ chức) sinh hai dòng.
- **Chế tài có điều kiện:** câu có "trong trường hợp…", "nếu…", "mà…", "(khi…)" không ghi vào `tru_diem_gplx`/`tuoc_gplx_*`/`bien_phap_bo_sung` mà vào `attributes.che_tai_co_dieu_kien` (167 dòng), kèm nguyên văn điều kiện. Vd chủ xe chỉ bị trừ điểm khi trực tiếp điều khiển. **M7 phải đọc trường này**, nếu không câu trả lời sẽ thiếu.
- **Thêm ngoài spec:** Phạt cảnh cáo → `bien_phap_bo_sung = {Phạt cảnh cáo}`, không có tiền. Khoản "Tịch thu phương tiện" có hành vi riêng → dòng không có tiền. Phạt theo đầu người → `attributes.tinh_theo = moi_nguoi`, `tong_muc_phat_toi_da`. Thêm chiều `tai_pham`, giá trị `khong_chap_hanh` ở `nong_do_con`.
- **Mã phương tiện thêm:** `xe_4_banh_dong_co`, `may_keo`, `xe_tho_so`, `hanh_khach`, `co_gioi`, `khong_ap_dung`. Điều 12, 26, 31, 39, 40 không gắn với loại xe nên dùng `khong_ap_dung` (`dieu_defaults`); nghĩa là bộ lọc phương tiện ở M7 phải cho qua giá trị này. Ưu tiên: câu dẫn → tiêu đề Điều → hành vi → mặc định theo Điều.
- **Lỗi đã bắt được khi đối chiếu:** "mô tô" chứa chuỗi "ô tô" nên xe máy bị gắn `o_to` (đã sửa bằng `\\b`, có test).
- **`quality/checks.py`:** đủ 6 rule spec 8.6, mỗi rule có test. Chồng lấn thời gian dừng job. Sai `min <= max` thì loại khỏi bảng và quarantine. Số Điều và `target_key` sai ghi quarantine. Số pass/warn/error nằm ở `stats["quality"]` (log `build_gold_done`), chưa có bảng metrics riêng.
- **Kết quả:** 906 dòng, 666 mục, 0 `needs_review`, 0 Điểm trong Khoản phạt bị bỏ sót, 1 mục quarantine: Điều 39 khoản 8 (giáo viên vi phạm Điều 6 bị xử theo Điều 6, không có mức riêng). Mẫu 50 dòng: [M5_SAMPLE_CHECK.md](M5_SAMPLE_CHECK.md).
- **Giới hạn:** LLM (spec 8.5 bước 5, tuỳ chọn) chưa dùng. Hành vi là cả Điểm, Điểm gom nhiều hành vi không được tách. `doi_tuong` để trống ở các Điều cơ sở đào tạo, đăng kiểm (66 dòng).
- **Nghiệm thu "kiểm tra tay":** Claude đối chiếu với text đã parse. Nhóm cần người đọc lại mẫu nếu muốn đúng nghĩa kiểm tra tay.

## D-020. Index và retrieval (M6, 31/10/2026)
- **Lệch spec 9.2 (keyword):** dùng `to_tsquery` nối từ bằng OR, bỏ từ dừng (`retrieval.stopwords`), thay cho `plainto_tsquery`. Plainto là AND: câu hỏi tự nhiên hiếm khi có đủ mọi từ trong một điều khoản nên nhánh keyword gần như luôn rỗng.
- **Nhánh vector:** quét đúng sau khi lọc hiệu lực (CTE `MATERIALIZED`), không đi qua HNSW, vì HNSW lọc sau khi duyệt và có thể thiếu kết quả. Bảng 3.545 dòng nên vẫn nhanh. Cần xem lại nếu dữ liệu lớn nhiều lần.
- **Lệch spec 8.7:** `build_index` đọc Gold đã nạp Postgres, không chạy Spark: embedding chạy trong một tiến trình, Spark không giúp gì. So sánh trực tiếp `embed_text` thay cho hash.
- **Chunk:** bỏ 4 văn bản sửa đổi (Luật 118, NĐ 184, NĐ 236, NĐ 238) vì nội dung đã vào phiên bản của văn bản đích. Hệ quả: phần riêng của chúng không tìm được, gồm điều khoản chuyển tiếp NĐ 238 và NĐ 236, nội dung phân định thẩm quyền của NĐ 184. Một phiên bản Điểm tách nhiều chunk khi câu dẫn Khoản đổi (`{key}@v{n}#2`).
- **`max_seq_length = 512`** (`embedding` trong settings), không phải 8192 mặc định của bge-m3.
- **Kết quả trên 66 câu bản nháp (46 câu chung, 20 câu kiểm tra phiên bản):**
| Cấu hình | Recall@5 | Recall@20 | MRR@5 | Đúng phiên bản | Bản sai xếp trước |
|---|---|---|---|---|---|
| Vector, có lọc | 74,2% | 89,4% | 0,552 | 80,0% | 0 |
| Keyword, có lọc | 68,2% | 80,3% | 0,477 | 80,0% | 0 |
| Hybrid, không lọc hiệu lực | 74,2% | 90,9% | 0,522 | 80,0% | 9 |
| Hybrid + lọc hiệu lực | 77,3% | 90,9% | 0,575 | 85,0% | 0 |
- **Vì sao trượt (15 câu):** (1) cùng hành vi ở nhiều Điều theo loại xe, xếp nhầm Điều (xe máy ↔ xe máy chuyên dùng); (2) từ đời thường khác chữ luật: "vượt đèn đỏ" ↔ "không chấp hành hiệu lệnh của đèn tín hiệu", "bằng lái" ↔ "giấy phép lái xe"; (3) đáp án nháp quá hẹp: "chở vượt trọng tải" có nhiều bậc theo tỷ lệ % ở các khoản khác nhau.
- **Việc nên làm:** nhóm (1) dùng slot phương tiện để ưu tiên ở M7. Nhóm (2) cần từ điển đồng nghĩa. Chưa làm, vì chỉnh theo chính bộ câu hỏi này dễ làm số liệu đẹp giả.
- **Đáp án eval là bản nháp** do Claude soạn từ dữ liệu đã parse, chưa được nhóm đối chiếu (spec 16.1). Hybrid không lọc vẫn có Recall@20 cao vì `is_hit` chỉ tính đúng phiên bản; cột cuối mới cho thấy tác dụng của bộ lọc.

## D-021. Câu hỏi phụ, trả lời, API (M7, 01/11/2026)
- **Ngưỡng `not_found` (spec 11.2 mục 4):** cosine của chunk tốt nhất ≥ 0,55 (`qa.min_similarity`). Đo trên 12 câu thử: câu giao thông ≥ 0,65, câu lạc đề ≤ 0,51. Mẫu nhỏ, cần đo lại khi có bộ câu hỏi lạc đề.
- **Ứng viên:** chunk trong `candidate_chunks` đầu và có cosine ≥ cosine tốt nhất − `similarity_margin`, vì điểm RRF không so được giữa các câu. Thiếu bước này, "vượt đèn đỏ" bị hỏi nồng độ cồn.
- **Lệch spec 10.2 bước 4:** spec trả `not_found` khi không có violation. Câu hỏi về quy định ("xe máy được chở mấy người") không có violation nhưng có điều khoản, nên câu không có ý hỏi mức phạt (`RE_PENALTY_INTENT`) được trả lời bằng trích nguyên văn, không có `facts`.
- **Lệch spec 10.2 bước 3:** mục `khong_ap_dung`/`co_gioi` chỉ dùng khi không có mục đúng loại xe.
- **Chưa làm:** chiều `thoi_diem` (spec 10.2). Ứng viên hiện lọc đúng một ngày nên không có nhiều version để hỏi; người dùng đổi `as_of_date` hoặc nêu ngày trong câu. Thống kê "câu hỏi liên quan" từ `qa_sessions` chờ có dữ liệu.
- **Mở rộng truy vấn (`retrieval.query_expansions`):** thêm 5 cụm từ đời thường → chữ luật. Đảo quyết định ở D-020: "vượt đèn đỏ" là câu hỏi phổ biến, trả sai mức phạt nặng hơn việc số đo khó diễn giải. Recall@5 từ 77,3% lên 87,9%, Recall@20 từ 90,9% lên 92,4%, **nhưng các cụm này chọn sau khi xem câu trượt của chính bộ eval**, nên số mới lạc quan. Cần đo lại trên câu hỏi mới.
- **LLM:** `LLM_API_KEY` trống → câu trả lời dạng template, đủ con số, trích dẫn và chế tài có điều kiện. Có khoá → `claude-opus-5-5`, effort `low`, bật `fallbacks: "default"` (server-side fallback khi bị từ chối). Provider khác chưa viết. Chế độ LLM đã test bằng client giả, **chưa chạy với API thật**.
- **Q-1 (topic của event):** đề xuất tạm: chiều đang hỏi, hoặc thuộc tính phân biệt của fact đầu, hoặc `unknown`. Thay cho đề xuất cũ.
- **Feedback:** spec không có bảng nên chỉ ghi event; ghi chú (`note`) chưa được lưu. Không lưu định danh người dùng.
- **`luatgt.qa.service`** là module thêm ngoài spec 4, gom luồng để API mỏng. `/api/health` chỉ báo model đã nạp hay chưa.
- **Sửa ở M5:** hành vi của Khoản không có Điểm bị dính vế tiền ("cá nhân, từ 4.000.000…") ở câu dẫn hai mức.
- **Nghiệm thu trên dữ liệu thật (server uvicorn, model thật):** xem README. Số liệu lấy từ `violations`.

## D-022. Frontend (M8, 01/11/2026)
- **Bổ sung API ngoài spec 12:** `GET /api/documents/{id}/provisions?as_of=` trả cây điều khoản tại một ngày (kèm `added`: 57 điều khoản do văn bản sửa đổi bổ sung, có version nhưng không có dòng `provisions`). `GET /api/documents` trả thêm `tinh_trang_norm`, `ngay_ban_hanh` và lọc theo giá trị chuẩn hoá. Chi tiết văn bản có `incoming` và khớp `dst_vbpl_id` qua số hiệu vì cột này thường rỗng.
- **Trình duyệt gọi API qua rewrite của Next** (`API_URL`), cùng origin nên không cần CORS.
- **Badge trong panel nguyên văn là hiệu lực của chính điều khoản tại ngày áp dụng,** không phải của cả văn bản: điều khoản đang áp dụng của NĐ 168 không được hiện "hết hiệu lực một phần".
- **Lệch spec 15.3.5:** so sánh phiên bản xếp dọc, không hai cột, vì panel chỉ rộng 440px. Dùng icon Lucide thay emoji 👍/👎.
- **Thiếu:** số trang PDF: `pdf_page` đang rỗng ở toàn bộ 4.651 điều khoản nên panel không hiện. Trang `/dashboard` và link của nó để M9. Hỏi ngữ cảnh chưa có: câu hỏi mới luôn tạo phiên mới.

## D-023. Streaming và dashboard (M9, 01/11/2026)
- **Lệch spec 12:** API không ghi nối vào file theo ngày nữa mà ghi mỗi event một file, đổi tên nguyên tử từ `events/.tmp/`. File source của Spark đọc mỗi file đúng một lần, nên dòng nối vào file đã đọc sẽ mất hẳn. Giá phải trả là nhiều file nhỏ; lưu lượng lớn thì chuyển Kafka.
- **Thêm ngoài spec:** bỏ event có `event_time` vượt `ingest_time` quá `streaming.max_client_ahead` (5 phút). Thiếu bước này, một client đặt sai đồng hồ đẩy watermark đi xa và làm mất mọi event thật sau đó. Event này không được đếm ở đâu cả.
- **`client_sent_at` không có múi giờ** được coi là giờ `timezone` trong settings.
- **Cách Spark loại event trễ:** so với watermark của batch trước, không phải batch hiện tại. Một event quá hạn có thể vẫn được đếm nếu vừa đến ngay batch watermark nhảy lên.
- **Chạy:** `luatgt stream` chạy liên tục, `luatgt stream --once` xử lý hết rồi dừng. `numRowsDroppedByWatermark` chỉ ghi log.
- **Thí nghiệm:** `eval/run_watermark_experiment.py`, kết quả ở [M9_WATERMARK.md](M9_WATERMARK.md). Có thêm mức đối chứng 60 phút để chứng minh phần thiếu chỉ do watermark. Dữ liệu là giả lập, tỉ lệ trễ 8% là tự chọn nên con số chỉ dùng để so sánh hai mức.
- **Đề xuất watermark:** giữ 10 phút như spec cho đến khi có phân bố trễ thật; chưa đo mức 10 phút trong thí nghiệm.
- **Dashboard:** thêm `GET /api/stats/summary`. "Tỉ lệ không hài lòng" là 👎 / số câu hỏi, không phải / số phản hồi, vì `qa_topic_counts` không đếm 👍. Bảng màu spec không đạt kiểm tra độ sáng của validator (vàng, xanh lá) và có cặp cam–xanh lá khó phân biệt với người mù màu đỏ–lục: bỏ cam, thêm viền đen, chú giải chữ và bảng số liệu. Biểu đồ 24 giờ gộp 30 phút, 7 ngày gộp 6 giờ.
- **Quarantine theo run:** 30/31 bản ghi không có `run_id` vì sinh ở bước parse/build, nên bảng theo run gần như toàn 0 và dashboard ghi số không gắn run riêng.

## D-024. Airflow và báo cáo eval (M10, 01/11/2026)
- **Lệch spec 3 và 4:** Airflow 2.11 chạy trên máy (`scripts/airflow.sh`, virtualenv `.venv-airflow`), không có trong `docker-compose.yml`. Crawler phải chạy headed trên máy có màn hình (D-007); Airflow trong Docker sẽ cần Xvfb, Chromium, Java và model bge-m3 trong cùng image. Virtualenv tách riêng vì constraints của Airflow xung đột với pipeline. Task gọi CLI bằng `BashOperator`.
- **Q-2 đã chốt:** `dag_build` chạy theo Airflow Dataset `luatgt://bronze`, chỉ phát khi `crawl_download` thành công. Crawl bị chặn hoặc `partial` làm task fail nên không build dữ liệu dở. Task crawl không retry (spec 7.2).
- **Lệch spec 14:** không có task `follow_relations` vì crawler giai đoạn 1 chỉ có mode `seed`. `quality_checks` không tách task riêng: kiểm tra nằm trong `build_gold`, lỗi error dừng trước khi publish, nên đúng yêu cầu Gold cũ vẫn phục vụ. Thêm task `bootstrap` (migrate, tạo bucket) và `dag_stream` mỗi 10 phút.
- **macOS:** thư viện `setproctitle` làm mọi tiến trình fork của Airflow SIGSEGV (đã xác nhận qua crash report), nên `scripts/airflow.sh` nạp bản rỗng ở `scripts/airflow_shim/`.
- **Executor:** `airflow standalone` dùng SQLite và chạy tuần tự, chỉ hợp với máy dev.
- **Chạy từ đầu:** dùng DB `luatgt_e2e`, bucket `e2e-*`, thư mục `data/e2e/` qua biến môi trường, không xoá Bronze hay Gold thật.
- **Nghiệm thu 01/11/2026:** kích hoạt `dag_crawl_daily` trên DB và bucket rỗng, `dag_build` tự chạy theo Dataset, `dag_eval` sinh báo cáo. DB e2e có đúng số dòng của DB thật (9 văn bản, 4.651 điều khoản, 449 sửa đổi, 5.032 phiên bản, 906 violations, 3.545 chunks, 31 quarantine) và trùng md5 trên `violations`, `provision_versions`. Kết quả này cho thấy pipeline tái lập được, không chứng minh dữ liệu đúng.
- **Eval:** Q&A chạy luồng thật bằng template, câu hỏi phụ trả lời theo đáp án chuẩn. "Dòng đầu đúng mức phạt" là thước đo thô: câu trả lời nhiều dòng có thể chứa mức đúng ở dòng sau. Bộ câu hỏi mới có 66/100 câu, đáp án chưa được nhóm đối chiếu; không tự sinh thêm cho đủ vì đáp án cần người kiểm. Parse accuracy và Extraction accuracy cần kiểm tay nên báo cáo ghi là chưa đo.

## Câu hỏi mở (cần nhóm quyết định trước milestone liên quan)
- **Q-1 (M9):** trường `topic` của event: đã áp dụng tạm theo D-021, chờ nhóm xác nhận.
- **Q-4:** NĐ 336/2025/NĐ-CP sửa NĐ 168/2024/NĐ-CP theo metadata vbpl.vn nhưng không có trong seed, cùng NĐ 319/2026 và Luật 143/2025. Có thêm vào kho không?
- **Q-3:** mục 0 của spec ghi "Milestone ở mục 14", thực tế là mục 17.
