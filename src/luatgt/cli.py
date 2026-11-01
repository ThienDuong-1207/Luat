"""CLI `luatgt`. M0: db migrate, storage init, health. Các lệnh crawl/reparse bổ sung ở M1–M3."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import typer

from luatgt.common.config import get_settings
from luatgt.common.logging import setup_logging

app = typer.Typer(help="LuậtGT: pipeline văn bản luật giao thông.", no_args_is_help=True)
db_app = typer.Typer(help="Thao tác PostgreSQL.", no_args_is_help=True)
storage_app = typer.Typer(help="Thao tác object storage (MinIO).", no_args_is_help=True)
app.add_typer(db_app, name="db")
app.add_typer(storage_app, name="storage")


@app.callback()
def _main() -> None:
    setup_logging(get_settings().log_level)


@db_app.command("migrate")
def db_migrate() -> None:
    """Áp các migration trong db/migrations chưa chạy."""
    from luatgt.common.db import migrate

    applied = migrate()
    typer.echo(f"Đã áp {len(applied)} migration: {', '.join(applied) or '(không có mới)'}")


@storage_app.command("init")
def storage_init() -> None:
    """Tạo các bucket bronze/silver/gold nếu chưa có."""
    from luatgt.common.storage import Storage

    created = Storage().ensure_buckets()
    typer.echo(f"Bucket mới: {', '.join(created) or '(đã đủ)'}")


@app.command("crawl")
def crawl(
    mode: str = typer.Option("seed", help="seed | search | follow_relations (M2)"),
    limit: int | None = typer.Option(None, help="Giới hạn số văn bản"),
    save_fixtures: Path | None = typer.Option(
        None, "--save-fixtures", help="M1: lưu HTML mọi tab vào thư mục này rồi thoát"
    ),
    url: list[str] = typer.Option(
        [], "--url", help="URL chi tiết cho --save-fixtures (mặc định: seed có url)"
    ),
    screenshots: bool = typer.Option(True, help="Chụp màn hình kèm fixtures"),
) -> None:
    """Crawl vbpl.vn."""
    import asyncio

    import yaml

    from luatgt.crawler.browser import BlockedError
    from luatgt.crawler.fixtures import save_fixtures as _save_fixtures
    from luatgt.crawler.selectors import load_source_config

    settings = get_settings()
    source = load_source_config(settings.path(settings.paths.vbpl_source))

    if save_fixtures is None:
        from luatgt.crawler.run import run_crawl

        run_id, status = asyncio.run(run_crawl(settings, mode=mode, limit=limit))
        typer.echo(f"Run {run_id}: {status}")
        raise typer.Exit({"success": 0, "partial": 1, "blocked": 3}.get(status, 2))

    urls = list(url)
    if not urls:
        seeds = yaml.safe_load(settings.path(settings.paths.seed_documents).read_text("utf-8"))
        urls = [d["url"] for d in seeds["documents"] if d.get("url")]
    urls = urls[:limit] if limit else urls
    try:
        manifest = asyncio.run(
            _save_fixtures(urls, settings.path(save_fixtures), settings, source, screenshots)
        )
    except BlockedError as e:
        typer.echo(f"BỊ CHẶN, dừng run: {e}")
        raise typer.Exit(3) from e
    typer.echo(f"Đã lưu {len(manifest)} fixture vào {save_fixtures}")


@app.command("reparse")
def reparse(
    all_docs: bool = typer.Option(False, "--all", help="Parse lại mọi văn bản trên Bronze"),
    vbpl_id: list[str] = typer.Option([], "--vbpl-id", help="Chỉ parse văn bản này (lặp được)"),
) -> None:
    """Bronze → Silver (Spark). Mặc định: văn bản có needs_reparse = true. Không crawl lại."""
    from luatgt.jobs.build_silver import build_silver

    stats = build_silver(get_settings(), all_docs=all_docs, ids=list(vbpl_id) or None)
    typer.echo(
        f"Silver: {stats['documents']} văn bản, {stats['provisions']} điều khoản, "
        f"{stats['issues']} vấn đề cần kiểm tra, {stats['uploaded']} file Parquet"
    )


@app.command("build-gold")
def build_gold_cmd() -> None:
    """Silver → Gold: phiên bản điều khoản (SCD2), violations, nạp Postgres. Dừng nếu có lỗi chất lượng."""
    from luatgt.jobs.build_gold import QualityError, build_gold

    try:
        s = build_gold(get_settings())
    except QualityError as e:
        typer.echo(f"DỪNG: {e}")
        raise typer.Exit(1) from e
    typer.echo(
        f"Gold: {s['versions']} phiên bản ({s['multi_version_keys']} điều khoản có > 1 phiên bản), "
        f"{s['amendments']} amendments, {s['violations']} violations, {s['quarantine_amend']} mục chờ xử lý tay"
    )


@app.command("stream")
def stream(once: bool = typer.Option(False, "--once", help="Xử lý hết event hiện có rồi dừng")) -> None:
    """Đếm event theo cửa sổ và upsert vào `qa_topic_counts`."""
    from luatgt.streaming.qa_events_stream import run_stream

    typer.echo(run_stream(once=once))


@app.command("build-index")
def build_index_cmd() -> None:
    """Gold → chunks + embedding. Chỉ embed lại chunk có nội dung đổi."""
    from luatgt.jobs.build_index import build_index

    typer.echo(build_index(get_settings()))


@app.command("search")
def search_cmd(
    question: str,
    as_of: str = typer.Option(None, "--as-of", help="YYYY-MM-DD; mặc định lấy từ câu hỏi hoặc hôm nay"),
    k: int = typer.Option(5, "--k"),
) -> None:
    """Tìm điều khoản theo câu hỏi tại một thời điểm."""
    from luatgt.common.db import make_engine
    from luatgt.retrieval.embed import SentenceTransformerEmbedder
    from luatgt.retrieval.query import parse_question
    from luatgt.retrieval.search import hybrid_search

    settings = get_settings()
    when = date.fromisoformat(as_of) if as_of else parse_question(question).as_of
    hits = hybrid_search(make_engine(settings), SentenceTransformerEmbedder(settings), question, when,
                         settings.retrieval, k=k)
    typer.echo(f"Tại {when}:")
    for h in hits:
        fine = next((v for v in h.violations if v["muc_phat_max"]), None)
        money = f" [{fine['muc_phat_min']:,}–{fine['muc_phat_max']:,} đ]" if fine else ""
        typer.echo(f"{h.score:.4f} {h.provision_key}@v{h.version_no}{money} {h.display_text[:90]}")


@app.command("provision")
def provision_cmd(
    key: str = typer.Argument(..., help="provision_key, vd 168-2024-ND-CP/D6/K3/Pm"),
    as_of: str | None = typer.Option(None, "--as-of", help="YYYY-MM-DD (mặc định hôm nay)"),
) -> None:
    """Nội dung điều khoản có hiệu lực tại một thời điểm, kèm lịch sử phiên bản."""
    from zoneinfo import ZoneInfo

    from sqlalchemy import text

    from luatgt.common.db import get_engine

    settings = get_settings()
    when = date.fromisoformat(as_of) if as_of else __import__("datetime").datetime.now(
        ZoneInfo(settings.timezone)).date()
    with get_engine().connect() as conn:
        rows = conn.execute(text("""
            SELECT version_no, valid_from, valid_to, source_vbpl_id, text,
                   (valid_from <= :d AND :d < valid_to) AS active
            FROM provision_versions WHERE provision_key = :k ORDER BY version_no"""),
            {"k": key, "d": when}).all()
    if not rows:
        typer.echo("Không có điều khoản này.")
        raise typer.Exit(1)
    for r in rows:
        mark = "▶" if r.active else " "
        to = "" if r.valid_to.year == 9999 else str(r.valid_to)
        typer.echo(f"{mark} v{r.version_no} [{r.valid_from} → {to}) nguồn {r.source_vbpl_id}")
    active = next((r for r in rows if r.active), None)
    typer.echo(f"\nTại {when}: " + ("không có hiệu lực" if active is None else
                                     (active.text or "(đã bãi bỏ)")))


@app.command("health")
def health() -> None:
    """Kiểm tra kết nối Postgres và MinIO."""
    from luatgt.common.db import ping
    from luatgt.common.storage import Storage

    ok = True
    for name, check in (("postgres", ping), ("minio", lambda: Storage().ping())):
        try:
            check()
            typer.echo(f"{name}: ok")
        except Exception as e:  # noqa: BLE001 - báo lỗi kết nối cho người dùng
            ok = False
            typer.echo(f"{name}: LỖI {type(e).__name__}: {e}")
    raise typer.Exit(0 if ok else 1)


if __name__ == "__main__":
    app()
