"""Sinh event giả lập có trễ và trùng cố ý cho thí nghiệm watermark (spec 13.2).

Mỗi file `part-*.jsonl` là một phút đến nơi, theo thời gian đến chứ không theo event time.
`truth.json` ghi số đếm đúng tuyệt đối (sau khi khử trùng) để đo độ đầy đủ.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

TOPICS = ["nong_do_con", "phuong_tien", "toc_do", "den_tin_hieu", "giay_to", "unknown"]
START = datetime(2026, 1, 5, 8, 0, tzinfo=UTC)
WINDOW_MINUTES = 10


@dataclass(frozen=True)
class GenConfig:
    n_events: int = 6000
    minutes: int = 180
    late_rate: float = 0.08       # tỉ lệ event đến trễ
    max_late_minutes: int = 25    # trễ phân bố đều trong 2..25 phút, vượt qua cả hai watermark 5 và 15
    duplicate_rate: float = 0.03  # retry: cùng event_id, đến sau bản gốc
    down_rate: float = 0.12       # trong số event feedback
    feedback_rate: float = 0.2
    seed: int = 20260105


def _window_key(t: datetime) -> str:
    return t.replace(minute=t.minute - t.minute % WINDOW_MINUTES, second=0, microsecond=0).isoformat()


def generate(cfg: GenConfig) -> tuple[dict[int, list[dict]], dict]:
    """Trả về (phút đến → event, sự thật). Cùng seed cho cùng kết quả."""
    rng = random.Random(cfg.seed)
    arrivals: dict[int, list[dict]] = defaultdict(list)
    questions: Counter = Counter()
    downs: Counter = Counter()
    n_late = n_duplicates = 0

    for _ in range(cfg.n_events):
        event_at = START + timedelta(seconds=rng.uniform(0, cfg.minutes * 60))
        topic = rng.choice(TOPICS)
        kind = "feedback" if rng.random() < cfg.feedback_rate else "ask"
        thumbs = ("down" if rng.random() < cfg.down_rate else "up") if kind == "feedback" else None
        delay = rng.uniform(0, 30)
        if rng.random() < cfg.late_rate:
            delay = rng.uniform(120, cfg.max_late_minutes * 60)
            n_late += 1
        row = {"event_id": str(uuid.UUID(int=rng.getrandbits(128))), "event_time": event_at.isoformat(), "type": kind,
               "session_id": str(uuid.UUID(int=rng.getrandbits(128))), "topic": topic, "thumbs": thumbs,
               "client_sent_at": event_at.isoformat()}
        arrived = event_at + timedelta(seconds=delay)
        minute = int((arrived - START).total_seconds() // 60)
        arrivals[minute].append({**row, "ingest_time": arrived.isoformat()})
        if rng.random() < cfg.duplicate_rate:
            retry = arrived + timedelta(seconds=rng.uniform(1, 90))
            arrivals[int((retry - START).total_seconds() // 60)].append({**row, "ingest_time": retry.isoformat()})
            n_duplicates += 1
        key = f"{_window_key(event_at)}|{topic}"
        questions[key] += kind == "ask"
        downs[key] += thumbs == "down"

    truth = {"n_questions": sum(questions.values()), "n_thumbs_down": sum(downs.values()), "n_late": n_late,
             "n_duplicates": n_duplicates, "by_key": {k: [questions[k], downs[k]] for k in questions}}
    return arrivals, truth


def write_files(arrivals: dict[int, list[dict]], folder: Path) -> list[Path]:
    """Ghi từng phút một file; mtime tăng dần để Spark đọc đúng thứ tự đến."""
    folder.mkdir(parents=True, exist_ok=True)
    base = datetime.now(UTC).timestamp() - len(arrivals)
    paths = []
    for i, minute in enumerate(sorted(arrivals)):
        path = folder / f"part-{minute:05d}.jsonl"
        path.write_text("".join(json.dumps(r) + "\n" for r in arrivals[minute]), encoding="utf-8")
        os.utime(path, (base + i, base + i))
        paths.append(path)
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("out", type=Path)
    parser.add_argument("--events", type=int, default=GenConfig.n_events)
    args = parser.parse_args()
    arrivals, truth = generate(GenConfig(n_events=args.events))
    write_files(arrivals, args.out)
    (args.out / "_truth.json").write_text(json.dumps(truth), encoding="utf-8")
    print(f"{args.out}: {sum(map(len, arrivals.values()))} dòng, trễ {truth['n_late']}, trùng {truth['n_duplicates']}")


if __name__ == "__main__":
    main()
