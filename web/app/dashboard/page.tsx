import type { Metadata } from "next";
import { TopicChart, type TopicRow } from "@/components/TopicChart";
import { FilterChip } from "@/components/ui/Chip";
import { serverGet } from "@/lib/api";

export const metadata: Metadata = { title: "Dashboard · LuậtGT" };

const MINUTE = 60_000;
const RANGES = {
  "6h": { label: "6 giờ", span: 6 * 60, step: 10 },
  "24h": { label: "24 giờ", span: 24 * 60, step: 30 },
  "7d": { label: "7 ngày", span: 7 * 24 * 60, step: 6 * 60 },
};
type RangeKey = keyof typeof RANGES;

type Summary = {
  n_questions: number;
  n_thumbs_down: number;
  last_window_end: string | null;
  quarantine_by_stage: { stage: string; n: number }[];
  quarantine_by_run: { run_id: string; started_at: string; status: string; n: number }[];
  quarantine_without_run: number;
  last_run: { started_at: string; status: string } | null;
};

const RUN_STATUS: Record<string, string> = {
  running: "Đang chạy", success: "Thành công", partial: "Một phần", blocked: "Bị chặn", failed: "Lỗi",
};
const DATETIME = new Intl.DateTimeFormat("vi-VN", {
  timeZone: "Asia/Ho_Chi_Minh", hour: "2-digit", minute: "2-digit", day: "2-digit", month: "2-digit", year: "numeric",
});

function Tile({ label, value, note, tone }: { label: string; value: string; note?: string; tone: string }) {
  return (
    <div className={`rounded-brutal border-3 border-ink p-4 shadow-brutal ${tone}`}>
      <p className="label">{label}</p>
      <p className="mt-1 font-mono text-3xl font-extrabold leading-tight">{value}</p>
      {note ? <p className="mt-1 text-sm">{note}</p> : null}
    </div>
  );
}

export default async function DashboardPage({ searchParams }: { searchParams: Promise<{ range?: string }> }) {
  const requested = (await searchParams).range;
  const key: RangeKey = requested && requested in RANGES ? (requested as RangeKey) : "6h";
  const { span, step } = RANGES[key];
  const stepMs = step * MINUTE;
  const to = (Math.floor(Date.now() / stepMs) + 1) * stepMs;
  const from = to - span * MINUTE;
  const query = new URLSearchParams({ from: new Date(from).toISOString(), to: new Date(to).toISOString() });
  const [rows, summary] = await Promise.all([
    serverGet<TopicRow[]>(`/api/stats/topics?${query}`),
    serverGet<Summary>("/api/stats/summary"),
  ]);
  if (!summary) throw new Error("Thiếu số liệu tổng hợp");

  const openQuarantine = summary.quarantine_by_stage.reduce((n, s) => n + s.n, 0);
  const rate = summary.n_questions ? (summary.n_thumbs_down / summary.n_questions) * 100 : null;

  return (
    <main className="mx-auto w-full max-w-6xl space-y-6 px-4 py-6">
      <h1 className="text-4xl font-black leading-tight">Dashboard</h1>
      <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
        <Tile label="Tổng câu hỏi" value={summary.n_questions.toLocaleString("de-DE")} tone="bg-yellow"
          note={summary.last_window_end ? `Đến ${DATETIME.format(new Date(summary.last_window_end))}` : "Chưa có dữ liệu"} />
        <Tile label="Phản hồi không hài lòng" value={rate === null ? "—" : `${rate.toFixed(1).replace(".", ",")}%`} tone="bg-pink"
          note={`${summary.n_thumbs_down} phản hồi trên số câu hỏi`} />
        <Tile label="Quarantine chưa xử lý" value={String(openQuarantine)} tone="bg-blue"
          note={summary.quarantine_by_stage.map((s) => `${s.stage} ${s.n}`).join(" · ")} />
        <Tile label="Run gần nhất" value={summary.last_run ? RUN_STATUS[summary.last_run.status] ?? summary.last_run.status : "—"} tone="bg-green"
          note={summary.last_run ? DATETIME.format(new Date(summary.last_run.started_at)) : undefined} />
      </div>

      <nav aria-label="Khoảng thời gian" className="flex flex-wrap gap-2">
        {(Object.keys(RANGES) as RangeKey[]).map((k) => (
          <FilterChip key={k} href={`/dashboard?range=${k}`} active={k === key}>{RANGES[k].label}</FilterChip>
        ))}
      </nav>

      <TopicChart title={`Câu hỏi theo chủ đề, mỗi cột ${step < 60 ? `${step} phút` : `${step / 60} giờ`}`}
        rows={rows ?? []} metric="n_questions" from={from} to={to} stepMs={stepMs} />
      <TopicChart title="Phản hồi không hài lòng" rows={rows ?? []} metric="n_thumbs_down" from={from} to={to} stepMs={stepMs} />

      <section className="rounded-brutal border-3 border-ink bg-surface p-4 shadow-brutal">
        <h2 className="text-xl font-black">Quarantine theo run</h2>
        <table className="mt-4 w-full border-collapse text-sm">
          <thead>
            <tr className="bg-yellow">
              <th scope="col" className="label border-2 border-ink p-2 text-left">Run</th>
              <th scope="col" className="label border-2 border-ink p-2 text-left">Trạng thái</th>
              <th scope="col" className="label border-2 border-ink p-2 text-right">Số bản ghi</th>
            </tr>
          </thead>
          <tbody>
            {summary.quarantine_by_run.map((r) => (
              <tr key={r.run_id}>
                <td className="border-2 border-ink p-2 font-mono">{DATETIME.format(new Date(r.started_at))}</td>
                <td className="border-2 border-ink p-2">{RUN_STATUS[r.status] ?? r.status}</td>
                <td className="border-2 border-ink p-2 text-right font-mono">{r.n}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="mt-2 text-sm text-muted">
          {summary.quarantine_without_run} bản ghi sinh từ bước parse và build, không gắn với run crawl nào.
        </p>
      </section>
    </main>
  );
}
