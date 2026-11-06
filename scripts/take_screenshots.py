"""Chụp ảnh minh hoạ cho docs/THUYET_TRINH.md từ web đang chạy ở localhost:3000 (API ở :8000).

Dùng Chromium đi kèm Playwright, chạy ẩn (không dùng Chrome của máy). Ẩn nút dev "N" của Next.js trước khi chụp.
Chạy: .venv/bin/python scripts/take_screenshots.py docs/images
Mỗi lần chạy tạo vài phiên hỏi đáp trong qa_sessions, giống người dùng thật.
"""
import sys
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

OUT = Path(sys.argv[1])
OUT.mkdir(parents=True, exist_ok=True)
BASE = "http://localhost:3000"
HIDE_DEV = "nextjs-portal, [data-nextjs-toast], #__next-build-watcher {display:none !important}"


def prep(page: Page, path: str = "/") -> None:
    page.goto(BASE + path, wait_until="networkidle")
    page.add_style_tag(content=HIDE_DEV)


def set_date(page: Page, iso: str) -> None:
    page.locator('header input[type="date"]').fill(iso)


def ask(page: Page, question: str) -> None:
    page.get_by_label("Câu hỏi").fill(question)
    page.get_by_label("Câu hỏi").press("Enter")
    page.wait_for_selector('[role="status"] .loading-stripes', state="detached", timeout=90_000)
    page.wait_for_timeout(400)


def answer_followups(page: Page, values: list[str]) -> None:
    form = page.locator("main form").last
    for v in values:
        form.locator(f'input[type="radio"][value="{v}"]').check()
    form.get_by_role("button", name="XEM MỨC PHẠT").click()
    page.wait_for_selector('[role="status"] .loading-stripes', state="detached", timeout=90_000)
    page.wait_for_timeout(400)


def shot(page: Page, name: str, full: bool = False) -> None:
    page.screenshot(path=str(OUT / f"{name}.png"), full_page=full)
    print("saved", name)


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    desk = browser.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=1, locale="vi-VN",
                               timezone_id="Asia/Ho_Chi_Minh")
    page = desk.new_page()

    # 1. Trang chủ
    prep(page)
    shot(page, "01-trang-chu")

    # 2–3. Câu hỏi phụ dạng radio → kết quả, mở cột tham chiếu
    ask(page, "Uống rượu lái xe bị phạt bao nhiêu?")
    page.locator("main form").last.scroll_into_view_if_needed()
    page.locator('main form').last.locator('input[value="xe_may"]').check()
    page.locator('main form').last.locator('input[value="tren_80mg"]').check()
    shot(page, "02-cau-hoi-phu")
    page.locator('main form').last.get_by_role("button", name="XEM MỨC PHẠT").click()
    page.wait_for_selector('[role="status"] .loading-stripes', state="detached", timeout=90_000)
    page.wait_for_timeout(400)
    page.locator('main button[aria-label^="Mở nguyên văn Điểm d khoản 9 Điều 7"]').first.click()
    page.wait_for_selector("aside .legal", timeout=30_000)
    page.locator("main mark.fine").first.scroll_into_view_if_needed()
    page.mouse.move(0, 0)
    shot(page, "03-ket-qua-muc-phat")

    # 4. Câu hỏi về quy định → quy định + mức phạt liên quan
    prep(page)
    ask(page, "Chở hàng cồng kềnh")
    answer_followups(page, ["xe_may"])
    # Chụp riêng khung câu trả lời; ẩn ô nhập dính đáy để không đè vào giữa ảnh dài
    page.add_style_tag(content="form.sticky{display:none !important}")
    page.locator("main div.relative.overflow-hidden").last.screenshot(
        path=str(OUT / "04-quy-dinh-va-muc-phat-lien-quan.png"))
    print("saved 04-quy-dinh-va-muc-phat-lien-quan")

    # 5–6. Cùng câu hỏi, hai ngày áp dụng khác nhau
    q = "Chở trẻ em dưới 10 tuổi ngồi ghế trước ô tô bị phạt bao nhiêu?"
    for iso, name in [("2026-08-01", "05-phien-ban-truoc-sua-doi"), ("2026-10-20", "06-phien-ban-sau-sua-doi")]:
        prep(page)
        set_date(page, iso)
        ask(page, q)
        if page.locator("main form fieldset").count():
            answer_followups(page, ["o_to"])
        page.locator('main button[aria-label^="Mở nguyên văn Điểm m khoản 3 Điều 6"]').first.click()
        page.wait_for_selector("aside .legal", timeout=30_000)
        if name.startswith("06"):
            page.locator("aside").get_by_role("button", name="So sánh phiên bản").click()
            page.wait_for_timeout(500)
        page.locator("main .legal").last.scroll_into_view_if_needed()
        page.evaluate("window.scrollTo(0, 0)")
        page.mouse.move(0, 0)
        shot(page, name)

    # 7. Câu ngắn và câu lạc đề
    prep(page)
    ask(page, "không đội mũ bảo hiểm")
    page.evaluate("window.scrollTo(0, 0)")
    shot(page, "07-cau-ngan")
    prep(page)
    ask(page, "Công thức làm bánh mì")
    shot(page, "08-khong-tim-thay")

    # 9. Dashboard và danh sách văn bản
    prep(page, "/dashboard?range=7d")   # 7 ngày để biểu đồ có dữ liệu
    page.wait_for_timeout(800)
    shot(page, "09-dashboard", full=True)
    prep(page, "/van-ban")
    shot(page, "10-danh-sach-van-ban")

    # 11. Điện thoại: câu hỏi phụ
    mob = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True,
                              has_touch=True, locale="vi-VN", timezone_id="Asia/Ho_Chi_Minh")
    m = mob.new_page()
    prep(m)
    ask(m, "Uống rượu lái xe bị phạt bao nhiêu?")
    m.locator("main form").last.scroll_into_view_if_needed()
    m.locator('main form').last.locator('input[value="xe_may"]').check()
    shot(m, "11-dien-thoai-cau-hoi-phu")
    browser.close()
