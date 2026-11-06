"use client";

import { BookOpen, Send } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { Answer } from "@/components/Answer";
import type { Selection } from "@/components/FollowUpForm";
import { useAsOf } from "@/components/AsOfContext";
import { ProvisionAside, ProvisionPanel } from "@/components/ProvisionPanel";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { postJson, type AskResponse, type Citation } from "@/lib/api";
import { citationChipLabel, todayVn } from "@/lib/format";
import { useMediaQuery } from "@/lib/useMediaQuery";

type Turn = { id: number; role: "user"; text: string } | { id: number; role: "bot"; res: AskResponse; chosen?: Selection };
type Pending = { question: string; sessionId?: string; selected?: Record<string, string> };

const EXAMPLES = [
  { text: "Uống rượu lái xe bị phạt bao nhiêu?", tone: "bg-yellow" },
  { text: "Ô tô vượt đèn đỏ bị phạt thế nào?", tone: "bg-pink" },
  { text: "Xe máy không đội mũ bảo hiểm bị phạt bao nhiêu?", tone: "bg-green" },
  { text: "Quên bằng lái khi đi xe máy bị xử lý ra sao?", tone: "bg-blue" },
  { text: "Chạy quá tốc độ bị trừ bao nhiêu điểm?", tone: "bg-orange" },
  { text: "Trẻ em ngồi ô tô cần lưu ý quy định gì?", tone: "bg-surface" },
];
/** Từ cỡ này trở lên: 80% hỏi đáp, 20% cột tham chiếu cố định; nhỏ hơn thì nguyên văn mở trong panel bật lên. */
const WIDE = "(min-width: 1280px)";
const STEPS = ["Đang tìm điều khoản…", "Đang kiểm tra phiên bản…", "Đang soạn câu trả lời…"];

function Loading() {
  const [step, setStep] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setStep((s) => Math.min(s + 1, STEPS.length - 1)), 1500);
    return () => clearInterval(id);
  }, []);
  return (
    <div role="status">
      <div className="loading-stripes h-4 rounded-brutal border-2 border-ink" />
      <p className="mt-2 text-sm text-muted">{STEPS[step]}</p>
    </div>
  );
}

export function Chat() {
  const { asOf } = useAsOf();
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState("");
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState<Pending | null>(null);
  const [citation, setCitation] = useState<{ cite: Citation; asOf: string } | null>(null);
  const wide = useMediaQuery(WIDE);
  const nextId = useRef(0);
  const endRef = useRef<HTMLDivElement>(null);
  const latestRef = useRef<HTMLDivElement>(null);

  // Câu trả lời mới hiện từ đầu khối, không để người đọc rơi xuống cuối
  useEffect(() => {
    if (turns.at(-1)?.role === "bot") latestRef.current?.scrollIntoView({ block: "start" });
    else if (turns.length > 0) endRef.current?.scrollIntoView({ block: "end" });
  }, [turns.length]);

  async function run(request: Pending) {
    setLoading(true);
    setFailed(null);
    try {
      const res = await postJson<AskResponse>("/api/ask", {
        session_id: request.sessionId ?? null,
        question: request.question,
        as_of_date: asOf && asOf !== todayVn() ? asOf : null,
        selected: request.selected ?? null,
        client_sent_at: new Date().toISOString(),
      });
      setTurns((t) => [...t, { id: nextId.current++, role: "bot", res }]);
    } catch {
      setFailed(request);
    } finally {
      setLoading(false);
    }
  }

  function ask(question: string) {
    const text = question.trim();
    if (!text || loading) return;
    setDraft("");
    setTurns((t) => [...t, { id: nextId.current++, role: "user", text }]);
    run({ question: text });
  }

  function select(sessionId: string | null, selection: Selection) {
    if (!sessionId || loading) return;
    const text = Object.values(selection).map((o) => o.label).join(" · ");
    setTurns((t) => [
      ...t.map((turn, i) => (i === t.length - 1 && turn.role === "bot" ? { ...turn, chosen: selection } : turn)),
      { id: nextId.current++, role: "user" as const, text },
    ]);
    run({
      question: "",
      sessionId,
      selected: Object.fromEntries(Object.entries(selection).map(([dim, o]) => [dim, o.value])),
    });
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    ask(draft);
  }

  const lastBot = turns.findLastIndex((t) => t.role === "bot");
  const empty = turns.length === 0 && !loading && !failed;

  return (
    <div className="flex flex-1 flex-col xl:flex-row">
      <div className="flex min-w-0 flex-1 flex-col xl:w-4/5 xl:flex-none">
        <main className="mx-auto w-full max-w-chat flex-1 space-y-6 px-4 py-6 xl:max-w-none xl:px-8">
          {empty ? (
            <section className="space-y-6">
              <h1 className="text-4xl font-black leading-tight md:text-5xl">Hỏi về luật giao thông đường bộ</h1>
              <p className="text-muted">Trả lời theo văn bản còn hiệu lực tại ngày bạn chọn, kèm trích dẫn điều khoản.</p>
              <div className="grid gap-4 sm:grid-cols-2">
                {EXAMPLES.map((e) => (
                  <button key={e.text} type="button" onClick={() => ask(e.text)}
                    className={`brutal-press min-h-11 rounded-brutal border-3 border-ink p-4 text-left font-bold shadow-brutal ${e.tone}`}>
                    {e.text}
                  </button>
                ))}
              </div>
            </section>
          ) : null}

          <div aria-live="polite" className="space-y-6">
            {turns.map((turn, i) =>
              turn.role === "user" ? (
                <p key={turn.id} className="ml-auto w-fit max-w-[85%] rounded-brutal border-3 border-ink bg-yellow p-2 px-4 font-medium shadow-brutal-sm">
                  {turn.text}
                </p>
              ) : (
                <div key={turn.id} ref={i === lastBot ? latestRef : undefined} className="scroll-mt-4">
                  <Answer
                    res={turn.res}
                    active={i === lastBot && !loading}
                    chosen={turn.chosen}
                    onAsk={ask}
                    onSelect={(selection) => select(turn.res.session_id, selection)}
                    onCite={(cite) => setCitation({ cite, asOf: turn.res.as_of_date })}
                  />
                </div>
              ),
            )}
          </div>
          {loading ? <Loading /> : null}
          {failed ? (
            <div role="alert" className="flex flex-wrap items-center gap-4 rounded-brutal border-3 border-ink bg-orange p-4 font-bold">
              Chưa kết nối được máy chủ.
              <Button variant="secondary" onClick={() => run(failed)}>Thử lại</Button>
            </div>
          ) : null}
          <div ref={endRef} />
        </main>

        <form onSubmit={submit} className="sticky bottom-0 border-t-3 border-ink bg-paper p-4 pb-[max(1rem,env(safe-area-inset-bottom))]">
          <div className="mx-auto flex max-w-chat gap-2 xl:max-w-none xl:px-4">
            <Input
              aria-label="Câu hỏi"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              placeholder="Nhập câu hỏi về luật giao thông…"
              className="h-14 flex-1 shadow-brutal"
            />
            <Button type="submit" disabled={loading || !draft.trim()} className="h-14">
              <span className="hidden sm:inline">GỬI</span>
              <Send size={20} aria-hidden />
              <span className="sr-only sm:hidden">Gửi câu hỏi</span>
            </Button>
          </div>
        </form>
      </div>

      <aside aria-label="Tham chiếu luật"
        className="hidden border-ink bg-surface xl:sticky xl:top-0 xl:block xl:h-dvh xl:w-1/5 xl:self-start xl:border-l-3">
        {citation ? (
          <ProvisionAside
            provisionKey={citation.cite.provision_key}
            title={citationChipLabel(citation.cite)}
            asOf={citation.asOf}
            onClose={() => setCitation(null)}
          />
        ) : (
          <div className="p-4 text-sm text-muted">
            <BookOpen size={24} aria-hidden className="mb-2 text-ink" />
            <p className="label mb-1 text-ink">Tham chiếu luật</p>
            <p>Bấm vào trích dẫn Điều, Khoản, Điểm trong câu trả lời để xem nguyên văn và lịch sử phiên bản tại đây.</p>
          </div>
        )}
      </aside>

      {citation && !wide ? (
        <ProvisionPanel
          key={citation.cite.provision_key}
          provisionKey={citation.cite.provision_key}
          title={citationChipLabel(citation.cite)}
          asOf={citation.asOf}
          onClose={() => setCitation(null)}
        />
      ) : null}
    </div>
  );
}
