"use client";

import { ThumbsDown, ThumbsUp } from "lucide-react";
import { useState } from "react";
import ReactMarkdown from "react-markdown";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Chip, CitationChip } from "@/components/ui/Chip";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { Table, type Column } from "@/components/ui/Table";
import { postJson, type AskResponse, type Citation, type Fact } from "@/lib/api";
import { citationChipLabel, fineRange, formatDate, prepareAnswer, vehicleLabels } from "@/lib/format";

const COLUMNS: Column<Fact>[] = [
  { header: "Hành vi", cell: (f) => f.hanh_vi },
  { header: "Phương tiện", cell: (f) => vehicleLabels(f.phuong_tien) },
  { header: "Mức phạt", cell: fineRange, numeric: true },
  { header: "Trừ điểm", cell: (f) => f.tru_diem_gplx ?? "—", numeric: true },
  { header: "Tước GPLX", cell: (f) => f.tuoc_gplx ?? "—", numeric: true },
];

function Feedback({ sessionId }: { sessionId: string }) {
  const [sent, setSent] = useState<"up" | "down" | null>(null);
  const [failed, setFailed] = useState(false);

  async function send(thumbs: "up" | "down") {
    setFailed(false);
    try {
      await postJson("/api/feedback", { session_id: sessionId, thumbs, client_sent_at: new Date().toISOString() });
      setSent(thumbs);
    } catch {
      setFailed(true);
    }
  }

  return (
    <div className="flex items-center gap-4">
      <Button variant="secondary" aria-label="Câu trả lời hữu ích" aria-pressed={sent === "up"} onClick={() => send("up")}
        className={`px-0 shadow-brutal-sm ${sent === "up" ? "bg-green" : ""}`}>
        <ThumbsUp size={20} aria-hidden />
      </Button>
      <Button variant="secondary" aria-label="Câu trả lời chưa đúng" aria-pressed={sent === "down"} onClick={() => send("down")}
        className={`px-0 shadow-brutal-sm ${sent === "down" ? "bg-red" : ""}`}>
        <ThumbsDown size={20} aria-hidden />
      </Button>
      <span role="status" className="text-sm text-muted">
        {sent ? "Đã ghi nhận, cảm ơn bạn." : failed ? "Chưa gửi được, hãy thử lại." : ""}
      </span>
    </div>
  );
}

export function Answer({
  res,
  active,
  chosen,
  onSelect,
  onAsk,
  onCite,
}: {
  res: AskResponse;
  active: boolean;
  chosen?: string;
  onSelect: (dimension: string, option: { value: string; label: string }) => void;
  onAsk: (question: string) => void;
  onCite: (c: Citation) => void;
}) {
  const byId = new Map(res.citations.map((c) => [c.id, c]));
  const uncited = res.citations.filter((c) => !res.answer_markdown.split("Căn cứ:")[0].includes(`[${c.id}]`));
  return (
    <div className="space-y-6">
      <Card className="relative overflow-hidden p-4 pl-6">
        <span aria-hidden className="absolute inset-y-0 left-0 w-2 bg-yellow" />
        <p className="label mb-2">{res.status === "not_found" ? "Chưa tìm thấy" : res.status === "answered" ? "Trả lời" : "Cần làm rõ"}</p>
        <div className="legal">
          <ReactMarkdown
            components={{
              a({ href, children }) {
                const citation = href?.startsWith("#") ? byId.get(href.slice(1)) : undefined;
                if (!citation) return <span>{children}</span>;
                return (
                  <CitationChip aria-label={`Mở nguyên văn ${citation.label}`} onClick={() => onCite(citation)}>
                    {citationChipLabel(citation)}
                  </CitationChip>
                );
              },
            }}
          >
            {prepareAnswer(res.answer_markdown)}
          </ReactMarkdown>
        </div>
        {res.citations.length > 0 ? (
          <div className="mt-4">
            <p className="label mb-2">Áp dụng tại {formatDate(res.as_of_date)}</p>
            {uncited.length > 0 ? (
              <div className="flex flex-wrap gap-2">
                {uncited.map((c) => (
                  <CitationChip key={c.id} aria-label={`Mở nguyên văn ${c.label}`} onClick={() => onCite(c)}>
                    {citationChipLabel(c)}
                  </CitationChip>
                ))}
              </div>
            ) : null}
          </div>
        ) : null}
        {res.facts.length > 0 ? (
          <div className="mt-4 [overflow-wrap:anywhere]">
            <Table columns={COLUMNS} rows={res.facts} caption="Bảng mức phạt" />
          </div>
        ) : null}
        <div className="mt-4 space-y-4">
          <Disclaimer>{res.disclaimer}</Disclaimer>
          {res.status === "answered" && res.session_id ? <Feedback sessionId={res.session_id} /> : null}
        </div>
      </Card>

      {res.follow_up_questions.map((q) => (
        <section key={q.dimension}>
          <h3 className="label mb-2">{q.question}</h3>
          <div role="group" aria-label={q.question} className="grid grid-cols-2 gap-2 sm:flex sm:flex-wrap">
            {q.options.map((o) => (
              <Chip
                key={o.value}
                neutral={o.value === "__khong_ro__"}
                disabled={!active}
                className={chosen === `${q.dimension}:${o.value}` ? "bg-ink text-surface" : "disabled:opacity-60"}
                onClick={() => onSelect(q.dimension, o)}
              >
                {o.label}
              </Chip>
            ))}
          </div>
        </section>
      ))}

      {res.related_questions.length > 0 ? (
        <section>
          <h3 className="label mb-2">Câu hỏi liên quan</h3>
          <ul className="space-y-2">
            {res.related_questions.map((q) => (
              <li key={q}>
                <button type="button" disabled={!active} onClick={() => onAsk(q)}
                  className="min-h-11 w-full text-left text-sm font-medium underline underline-offset-4 disabled:text-muted disabled:no-underline">
                  {q}
                </button>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}
