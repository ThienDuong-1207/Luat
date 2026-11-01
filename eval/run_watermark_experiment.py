"""Thí nghiệm watermark 5 vs 15 phút và kiểm tra restart (spec 13.2, 17 M9). Không đụng `qa_topic_counts`.

Mỗi file là một micro-batch (`maxFilesPerTrigger=1`) nên kết quả lặp lại được và độ trễ đo theo thời gian mô phỏng.
Xuất `docs/M9_WATERMARK.md`.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import Engine, text

sys.path.insert(0, str(Path(__file__).parent))
from gen_events import WINDOW_MINUTES, GenConfig, generate, write_files

from luatgt.common.config import get_settings
from luatgt.common.db import make_engine
from luatgt.jobs.spark import get_spark
from luatgt.streaming.qa_events_stream import dropped_rows, start_query

TABLE = "qa_topic_counts_exp"
CONTROL_MINUTES = 60   # lớn hơn mọi độ trễ sinh ra: phải đúng tuyệt đối, chứng minh phần thiếu chỉ do watermark
REPORT = Path(__file__).parent.parent / "docs" / "M9_WATERMARK.md"


def vi(value: int | str) -> str:
    """6000 → "6.000", "93.62%" → "93,62%"."""
    return f"{value:,}".replace(",", ".") if isinstance(value, int) else value.replace(".", ",")


def reset_table(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(text(f"DROP TABLE IF EXISTS {TABLE}"))
        conn.execute(text(f"CREATE TABLE {TABLE} (LIKE qa_topic_counts INCLUDING ALL)"))


def read_table(engine: Engine) -> dict[str, tuple[int, int]]:
    with engine.connect() as conn:
        rows = conn.execute(text(f"SELECT window_start, topic, n_questions, n_thumbs_down FROM {TABLE}")).all()
    return {f"{r[0].astimezone(UTC).isoformat()}|{r[1]}": (r[2], r[3]) for r in rows}


def run(spark, settings, engine, source: Path, checkpoint: Path, watermark: str) -> list[dict]:
    query = start_query(spark, settings, engine, source, checkpoint, watermark=watermark, table=TABLE, max_files=1)
    query.awaitTermination()
    if query.exception():
        raise RuntimeError(str(query.exception()))
    return [json.loads(p.json) for p in query.recentProgress]


def closing_delay(progress: list[dict]) -> float:
    """Cửa sổ chốt khi watermark vượt `window_end`. Trả về trung bình (event time lớn nhất lúc chốt − window_end), phút."""
    delays, closed = [], None
    seen_max = None
    for p in progress:
        times = p.get("eventTime", {})
        if "max" in times:
            seen_max = datetime.fromisoformat(times["max"])
        mark = times.get("watermark")
        if not mark or seen_max is None:
            continue
        mark_ts = datetime.fromisoformat(mark).timestamp()
        if mark_ts <= 0:
            continue
        step = WINDOW_MINUTES * 60
        last_closed = int(mark_ts // step)
        if closed is not None:
            delays += [seen_max.timestamp() - w * step for w in range(closed + 1, last_closed + 1)]
        closed = last_closed
    return sum(delays) / len(delays) / 60 if delays else 0.0


def measure(spark, settings, engine, files: list[Path], work: Path, minutes: int, truth: dict) -> dict:
    reset_table(engine)
    source = work / f"src{minutes}"
    shutil.copytree(files[0].parent, source, copy_function=shutil.copy2)
    progress = run(spark, settings, engine, source, work / f"cp{minutes}", f"{minutes} minutes")
    got = read_table(engine)
    n_q = sum(v[0] for v in got.values())
    n_d = sum(v[1] for v in got.values())
    exact = sum(1 for k, want in truth["by_key"].items() if got.get(k) == tuple(want))
    return {"minutes": minutes, "n_q": n_q, "n_d": n_d, "completeness": n_q / truth["n_questions"],
            "exact_keys": exact, "n_keys": len(truth["by_key"]), "dropped": sum(map(dropped_rows, progress)),
            "delay": closing_delay(progress),
            "state": max(sum(o.get("numRowsTotal", 0) for o in p.get("stateOperators", [])) for p in progress)}


def check_restart(spark, settings, engine, files: list[Path], work: Path) -> dict:
    """So sánh chạy liền mạch với: dừng giữa chừng, chạy tiếp, rồi xoá commit cuối để ép chạy lại batch đã ghi sink."""
    wm = "10 minutes"
    reset_table(engine)
    clean_src = work / "clean"
    shutil.copytree(files[0].parent, clean_src, copy_function=shutil.copy2)
    run(spark, settings, engine, clean_src, work / "cp_clean", wm)
    baseline = read_table(engine)

    reset_table(engine)
    source = work / "restart"
    source.mkdir()
    half = len(files) // 2
    for f in files[:half]:
        shutil.copy2(f, source)
    checkpoint = work / "cp_restart"
    run(spark, settings, engine, source, checkpoint, wm)
    mid = read_table(engine)
    for f in files[half:]:
        shutil.copy2(f, source)
    run(spark, settings, engine, source, checkpoint, wm)

    commits = sorted((checkpoint / "commits").glob("[0-9]*"), key=lambda p: int(p.name))
    replayed = int(commits[-1].name)
    commits[-1].unlink()
    (checkpoint / "commits" / f".{replayed}.crc").unlink(missing_ok=True)
    rerun = run(spark, settings, engine, source, checkpoint, wm)
    after = read_table(engine)
    return {"baseline_keys": len(baseline), "mid_keys": len(mid), "replayed_batch": replayed,
            "replay_batches": [p["batchId"] for p in rerun if p.get("numInputRows")], "equal": after == baseline,
            "n_diff": sum(1 for k in baseline.keys() | after.keys() if baseline.get(k) != after.get(k))}


def main() -> None:
    settings = get_settings()
    engine = make_engine(settings)
    cfg = GenConfig()
    arrivals, truth = generate(cfg)
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        files = write_files(arrivals, work / "events")
        spark = get_spark(settings)
        spark.conf.set("spark.sql.streaming.numRecentProgressUpdates", "5000")
        spark.conf.set("spark.sql.streaming.noDataMicroBatches.enabled", "true")
        try:
            results = [measure(spark, settings, engine, files, work, m, truth) for m in (5, 15, CONTROL_MINUTES)]
            restart = check_restart(spark, settings, engine, files, work)
        finally:
            with engine.begin() as conn:
                conn.execute(text(f"DROP TABLE IF EXISTS {TABLE}"))

    rows = "\n".join(
        f"| {r['minutes']} phút{' (đối chứng)' if r['minutes'] == CONTROL_MINUTES else ''} | "
        f"{vi(r['n_q'])} / {vi(truth['n_questions'])} | {vi(format(r['completeness'], '.2%'))} | "
        f"{r['exact_keys']} / {r['n_keys']} | {r['n_d']} / {truth['n_thumbs_down']} | {r['dropped']} | "
        f"{vi(format(r['delay'], '.1f'))} phút | {vi(r['state'])} |" for r in results)
    report = f"""# M9: thí nghiệm watermark

Sinh bởi `eval/run_watermark_experiment.py`, seed {cfg.seed}.

**Dữ liệu:** {vi(cfg.n_events)} event trong {cfg.minutes} phút mô phỏng, {truth['n_late']} event trễ 2–{cfg.max_late_minutes} phút \
({cfg.late_rate:.0%}), {truth['n_duplicates']} event gửi trùng. Cửa sổ {WINDOW_MINUTES} phút, {len(files)} micro-batch, mỗi batch một phút đến.

| Watermark | Câu hỏi đếm được | Độ đầy đủ | Ô (cửa sổ, topic) đúng tuyệt đối | Thumbs down | Dòng bị watermark loại | Độ trễ chốt cửa sổ | State lớn nhất (dòng) |
|---|---|---|---|---|---|---|---|
{rows}

- **Độ trễ chốt cửa sổ:** trung bình từ lúc cửa sổ kết thúc đến lúc watermark vượt qua nó, tính theo thời gian mô phỏng. Output mode update vẫn hiện số tạm ngay; đây là lúc số không đổi nữa.
- **Số trùng** được khử hết trong phạm vi watermark; bản gốc bị loại vì trễ thì bản trùng cũng bị loại.

## Restart từ checkpoint (watermark 10 phút)

Chạy nửa đầu, dừng, chạy tiếp trên cùng checkpoint, rồi xoá commit của batch {restart['replayed_batch']} để ép Spark chạy lại batch đã ghi sink. So với một lần chạy liền mạch:

- Số ô (cửa sổ, topic) khác nhau: **{restart['n_diff']}** trên {restart['baseline_keys']} ô.
- Batch chạy lại có dữ liệu: {restart['replay_batches'] or 'không (batch cuối không còn dòng mới)'}.
- Kết quả: **{'khớp hoàn toàn' if restart['equal'] else 'LỆCH'}**.
"""
    REPORT.write_text(report, encoding="utf-8")
    print(report)
    if not restart["equal"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
