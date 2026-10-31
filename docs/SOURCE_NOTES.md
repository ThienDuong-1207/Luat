# Ghi chú cấu trúc vbpl.vn

Khảo sát ngày 23/10/2026 bằng Playwright Chromium (headed, xem DECISIONS D-007). Fixtures nằm ở `tests/fixtures/vbpl/`, danh sách và thời điểm tải trong `manifest.json`:

| vbpl_id | Văn bản | Ghi chú |
|---|---|---|
| `23289` | Luật 26/2001/QH10 | hết hiệu lực toàn bộ, không có file tải |
| `173920` | NĐ 168/2024/NĐ-CP | hết hiệu lực một phần, chỉ có file .doc |
| `f4b0c320-79e6-11f1-8c8a-3587e086d762` | NĐ 238/2026/NĐ-CP | ID dạng **UUID** (D-008), có .doc và .pdf |

Selector đặt trong `config/sources/vbpl.yaml` (`selector_version: 2026-10-23.v1`).

## Công nghệ trang
- Next.js (App Router) + Ant Design + Tailwind. Nội dung render phía client; payload RSC (`self.__next_f`) **không** chứa dữ liệu văn bản.
- Class có hash (`css-1rb9ewt`, `effStatus_statusTag__HpzlZ`, `DocumentCard_documentTitle__aE_F_`) đổi theo mỗi bản build → không dùng làm selector (riêng `[class*="documentTitle"]` ở trang tìm kiếm là ngoại lệ, đã ghi chú).
- Banner cookie (`.ida_modal`) chặn thao tác bấm. Crawler bấm **"Từ chối"** (`crawler.consent_decline_text`).
- Tải bằng `networkidle` đôi khi hết timeout (tab Lược đồ, Lệnh công bố) nhưng HTML vẫn đầy đủ → chỉ log warning.

## Tab và tham số `tabs=`
Mỗi tab chỉ render nội dung khi đang mở (panel khác rỗng) → mỗi tab là một lần tải `?tabs=…`.

| Tab hiển thị | `tabs=` | Khoá trong config | Panel |
|---|---|---|---|
| Nội dung | `toan-van` | `fulltext` | `[id$="-panel-toan-van"]` |
| Thuộc tính | `thuoc-tinh` | `attributes` | `[id$="-panel-thuoc-tinh"]` |
| Lược đồ | `luoc-do` | `related` | `[id$="-panel-luoc-do"]` |
| Lịch sử | `lich-su` | `history` | `[id$="-panel-lich-su"]` |
| Văn bản gốc | `hien-thi-pdf` | `original_file` | pdf.js vẽ lên `<canvas>`, không có link |
| Lệnh công bố | `lenh-cong-bo` | `promulgation` | trống ở cả 3 văn bản |
| Tải về | `tai-ve` | `download` | danh sách file, tải bằng nút |

Tab trống hiển thị "Không tìm thấy kết quả phù hợp".

## Metadata (tab Thuộc tính)
- Bảng Ant Design Descriptions: mỗi ô `.ant-descriptions-item-container` gồm `.ant-descriptions-item-label` + `.ant-descriptions-item-content`. **Trích theo nhãn** (`attribute_labels`), không theo vị trí.
- Tên văn bản: `.ant-descriptions-title` (đầy đủ, vd "Nghị định số 168/2024/NĐ-CP Quy định xử phạt…").
- Nhãn có: Số hiệu, Loại văn bản, Ngành, Lĩnh vực, Cơ quan ban hành, Chức danh, Người ký, Ngày ban hành, Ngày có hiệu lực, Ngày hết hiệu lực, Tình trạng hiệu lực.
- Ngày dạng `dd/mm/yyyy`. Giá trị trống hiển thị `--`.
- Tình trạng gặp: "Còn hiệu lực", "Hết hiệu lực một phần", "Hết hiệu lực toàn bộ" → `tinh_trang_map`.
- Đầu trang (ngoài tab) có `<h1>` tên văn bản, tình trạng, "Ngày có hiệu lực", "Ngày cập nhật", lượt xem.

## Văn bản liên quan (tab Lược đồ)
- Hai cột nhóm, mỗi nhóm là `.ant-card-body`, tiêu đề là `<span>` con trực tiếp dạng "Tên nhóm (n)", mục là `li > a`.
- **Mục không có href và không có ID** (bấm mở bằng JS). Số hiệu lấy từ text bằng regex (`so_hieu_in_text_regex`); mục không có số hiệu (vd "Hiến pháp năm 1992") giữ nguyên tên → `dst_vbpl_id = null`.
- Cột trái = văn bản đang xem tác động lên văn bản khác; cột phải = văn bản khác tác động lên văn bản đang xem. Ánh xạ sang `relation_type` trong `relation_groups` (D-009). Đã kiểm tra đối xứng: NĐ 238 "Văn bản bị tác động hiệu lực một phần" ∋ NĐ 168, và NĐ 168 "Văn bản quy định về việc hết hiệu lực một phần" ∋ NĐ 238.
- Nhóm lớn: Luật 26/2001 có "Văn bản áp dụng (307)" (không lưu), "Văn bản quy định chi tiết, hướng dẫn thi hành (47)".
- Giữa hai cột có khối "VĂN BẢN ĐANG XEM" lặp lại metadata.
- **Thứ tự mục không cố định**: tải lại cùng trang (23289) cho cùng 443 mục nhưng khác thứ tự → hash tab này sắp xếp `<li>` trước (`hash_unordered_list_tabs`, D-012).

## Lịch sử (tab Lịch sử), nguồn quan hệ sửa đổi tốt nhất
- Ant Table, dòng `tr.ant-table-row`, 3 ô: Thời gian, Trạng thái, Văn bản nguồn.
- Văn bản nguồn khác văn bản đang xem có **link kèm ID** (`a[href*="/van-ban/chi-tiet/"]`). Ngày = ngày sự kiện có hiệu lực (vd NĐ 168: "15/08/2026 – Văn bản bị sửa đổi, bổ sung – NĐ 238/2026").
- `data-row-key` có dạng `{id_nguồn|self}|{id_văn_bản}|{trạng thái}|{ngày}` (chưa dùng, để dự phòng).
- Trạng thái gặp: "Văn bản được ban hành", "Văn bản có hiệu lực", "Văn bản bị sửa đổi, bổ sung", "Văn bản hết hiệu lực toàn bộ" → `history_status`.

## File gốc (tab Văn bản gốc / Tải về)
- Tab Văn bản gốc hiển thị PDF bằng pdf.js trên `<canvas>` (NĐ 238: 14 trang); không có URL file trong DOM.
- Tab Tải về: mỗi file một khối (`.grid > div`): tên file, dung lượng, ngày tải lên, nút tải (`button`, **không có href**) → M2 tải bằng `page.expect_download()` khi bấm nút.
- Bấm nút tải → trình duyệt nhận sự kiện download bình thường (`page.expect_download()` dùng được, xác nhận ở run thật 23/10/2026). PDF của NĐ 238 (6.409.782 byte) **không có lớp chữ** (bản scan) → cần OCR nếu muốn khớp số trang.
- **Không phải văn bản nào cũng có PDF**: NĐ 168 chỉ có `168.2024.NĐ.CP.doc` (0.62MB); NĐ 238 có `.doc` (0.09MB) và `NĐ 238.2026.pdf` (6.11MB, nhiều khả năng là bản scan); Luật 26/2001 không có file (D-010).

## Cấu trúc HTML toàn văn (tab Nội dung)
- Vùng chứa: `[id$="-panel-toan-van"] .preview-content`.
- Luật 26/2001 và NĐ 238: các `<p>` thường (+ `<b>`, `<font>`), **không có class/thẻ đánh dấu Chương/Điều** → tách bằng regex (spec 8.3).
- NĐ 168: 532 KB, ngoài `<p>` còn có 51 **khối chú thích** (`div.rounded-md` chứa nút nhãn) bao quanh đoạn GỐC đã bị tác động: "Điều khoản được sửa đổi, bổ sung" (45), "Điều khoản được bổ sung" (3), "Điều khoản được bãi bỏ" (3). Văn bản hiển thị vẫn là bản gốc, không phải bản hợp nhất (vd điểm m khoản 3 Điều 6 còn câu cũ). Nội dung mới không có trong DOM (có thể nạp khi bấm nút).
- Lỗi gõ trong nguồn: NĐ 168 Điều 16 khoản 2, Điều 39 khoản 9, Điều 40 khoản 3 ghi "đ)" thay cho "d)"; Điều 40 khoản 3 còn "c)" lặp ở cuối (D-013).
- Văn bản sửa đổi (NĐ 238): "Điều 3. Sửa đổi, bổ sung điểm b khoản 8 Điều 13" rồi nội dung mới trong ngoặc kép; có khoản dạng **"1a."** ("Bổ sung khoản 1a vào trước khoản 1") → regex KHOẢN ở spec 8.3 (`^(\d+)\.`) cần mở rộng thành `^(\d+[a-zđ]?)\.` ở M3.
- Có dòng "Điều 6" đứng riêng (không có dấu chấm) trong NĐ 238 → kiểm tra kỹ ở M3/M4.

## Trang tìm kiếm / phân trang
- `https://vbpl.vn/van-ban/trung-uong`: ô `#keyword`, nút "Tìm kiếm", radio "Tìm kiếm trong" (Tất cả / Nội dung toàn văn / Tiêu đề / Số ký hiệu), bộ lọc nâng cao (loại văn bản, cơ quan, ngày, tình trạng hiệu lực…).
- **URL không đổi khi tìm kiếm** (trạng thái giữ trong JS) → không có URL template tìm kiếm.
- Kết quả là thẻ có tiêu đề bấm được (không có href); bấm mở **tab mới** tới trang chi tiết.
- Trang có **reCAPTCHA** (badge góc phải). Mode `search` tự động ở giai đoạn 2 cần đánh giá lại; không giải CAPTCHA.
- Phân trang: chưa khảo sát.
- Tìm "168/2024/NĐ-CP" ra 3 văn bản, gồm NĐ 168 và NĐ 238.

## Dấu hiệu bị chặn (challenge markers)
Quan sát 23/10/2026, Playwright Chromium **headless**, `locale=vi-VN`, không đổi User-Agent:
- Request đầu tiên (`/robots.txt`) và trang chi tiết 23289 đều trả **HTTP 403**.
- Trang chặn: `<title>403 Forbidden</title>`, nội dung "Sorry, you have been blocked", "You are unable to access <url>", kèm `Request-ID` và IP người truy cập. Mã Request-ID có dạng `…_PS-SGN-…`, cho thấy lớp WAF/CDN đặt tại Việt Nam.
- Cùng máy, cùng mạng, mở bằng trình duyệt thường thì **vào được** → không phải chặn theo IP mà là phát hiện trình duyệt tự động.
- Chế độ headed: mọi trang trả 200 (khoảng 35 lần tải trang trong ngày 23/10/2026, nghỉ 3–6 giây giữa các lần).
- Bản sao trang chặn (đã thay IP và Request-ID): `tests/fixtures/vbpl/blocked_403.html`. Chuỗi nhận diện trong `crawler.challenge_markers`.

## robots.txt
```
User-Agent: *
Allow: /
Disallow: /api/
Disallow: /Pages/
Sitemap: https://vbpl.vn/sitemap.xml
```
Trang chi tiết `/van-ban/chi-tiet/…` và `/van-ban/trung-uong` được phép. Crawler không gọi thẳng `/api/`. Sitemap chưa khảo sát (có thể dùng cho mode discover ở giai đoạn 2).
