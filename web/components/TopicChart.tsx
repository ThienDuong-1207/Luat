"use client";

import { useMemo, useState } from "react";

export type TopicRow = { window_start: string; topic: string; n_questions: number; n_thumbs_down: number };
type Metric = "n_questions" | "n_thumbs_down";

// Màu gắn với chủ đề, không theo thứ hạng; chủ đề ngoài danh sách gộp vào "Khác"
const SERIES = [
  { topic: "nong_do_con", label: "Nồng độ cồn", tone: "bg-yellow" },
  { topic: "phuong_tien", label: "Phương tiện", tone: "bg-blue" },
  { topic: "vuot_toc_do", label: "Tốc độ", tone: "bg-pink" },
  { topic: "unknown", label: "Chưa phân loại", tone: "bg-green" },
  { topic: "khac", label: "Khác", tone: "bg-surface" },
];
const KNOWN = new Set(SERIES.map((s) => s.topic));
const TIME = new Intl.DateTimeFormat("vi-VN", {
  timeZone: "Asia/Ho_Chi_Minh", hour: "2-digit", minute: "2-digit", day: "2-digit", month: "2-digit",
});

type Bar = { start: number; values: Record<string, number>; total: number };

function buildBars(rows: TopicRow[], metric: Metric, from: number, to: number, stepMs: number): Bar[] {
  const bars: Bar[] = [];
  for (let start = from; start < to; start += stepMs) bars.push({ start, values: {}, total: 0 });
  for (const row of rows) {
    const bar = bars[Math.floor((new Date(row.window_start).getTime() - from) / stepMs)];
    if (!bar) continue;
    const topic = KNOWN.has(row.topic) ? row.topic : "khac";
    bar.values[topic] = (bar.values[topic] ?? 0) + row[metric];
    bar.total += row[metric];
  }
  return bars;
}

export function TopicChart({ rows, metric, from, to, stepMs, title }: {
  rows: TopicRow[]; metric: Metric; from: number; to: number; stepMs: number; title: string;
}) {
  const bars = useMemo(() => buildBars(rows, metric, from, to, stepMs), [rows, metric, from, to, stepMs]);
  const [active, setActive] = useState<number | null>(null);
  const max = Math.max(1, ...bars.map((b) => b.total));
  const present = SERIES.filter((s) => bars.some((b) => b.values[s.topic]));
  const shown = active === null ? null : bars[active];
  const filled = bars.filter((b) => b.total > 0);

  return (
    <section className="rounded-brutal border-3 border-ink bg-surface p-4 shadow-brutal">
      <h2 className="text-xl font-black">{title}</h2>
      {present.length > 1 ? (
        <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-sm" aria-label="Chú giải">
          {present.map((s) => (
            <li key={s.topic} className="flex items-center gap-2">
              <span aria-hidden className={`size-4 border-2 border-ink ${s.tone}`} />
              {s.label}
            </li>
          ))}
        </ul>
      ) : null}
      <p className="mt-2 min-h-12 text-sm" aria-live="polite">
        {shown ? (
          <>
            <span className="font-mono font-bold">{TIME.format(shown.start)}</span>:{" "}
            {shown.total === 0 ? "không có dữ liệu" : present.flatMap((s) => (shown.values[s.topic] ? [`${s.label} ${shown.values[s.topic]}`] : [])).join(" · ")}
          </>
        ) : (
          <span className="text-muted">Đưa chuột hoặc chạm vào cột để xem số liệu.</span>
        )}
      </p>
      <div className="mt-2 flex gap-2">
        <div aria-hidden className="flex w-8 flex-col justify-between text-right font-mono text-xs text-muted">
          <span>{max}</span>
          <span>0</span>
        </div>
        <div className="flex h-56 flex-1 items-end gap-px border-b-3 border-ink" onPointerLeave={() => setActive(null)}>
          {bars.map((bar, i) => (
            <div key={bar.start} className="flex h-full min-w-0 flex-1 flex-col justify-end"
              onPointerEnter={() => setActive(i)} onPointerDown={() => setActive(i)}>
              <div className="flex flex-col-reverse overflow-hidden" style={{ height: `${(bar.total / max) * 100}%` }}>
                {present.map((s) => {
                  const value = bar.values[s.topic];
                  return value ? (
                    <div key={s.topic} className={`min-h-0 border-x border-t-2 border-ink ${s.tone}`} style={{ flexGrow: value, flexBasis: 0 }} />
                  ) : null;
                })}
              </div>
            </div>
          ))}
        </div>
      </div>
      <div aria-hidden className="ml-10 mt-1 flex justify-between font-mono text-xs text-muted">
        <span>{TIME.format(from)}</span>
        <span>{TIME.format(to)}</span>
      </div>
      <details className="mt-4 text-sm">
        <summary className="flex min-h-11 cursor-pointer items-center font-bold">Xem dạng bảng</summary>
        {filled.length === 0 ? <p className="text-muted">Chưa có dữ liệu trong khoảng này.</p> : (
          <div className="max-h-64 overflow-y-auto">
            <table className="w-full border-collapse">
              <caption className="sr-only">{title}</caption>
              <thead>
                <tr className="bg-yellow">
                  <th scope="col" className="label border-2 border-ink p-2 text-left">Thời điểm</th>
                  {present.map((s) => <th key={s.topic} scope="col" className="label border-2 border-ink p-2 text-right">{s.label}</th>)}
                </tr>
              </thead>
              <tbody>
                {filled.map((b) => (
                  <tr key={b.start}>
                    <td className="border-2 border-ink p-2 font-mono">{TIME.format(b.start)}</td>
                    {present.map((s) => <td key={s.topic} className="border-2 border-ink p-2 text-right font-mono">{b.values[s.topic] ?? 0}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </details>
    </section>
  );
}
