"use client";

import { ArrowRight } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Button } from "@/components/ui/Button";
import type { FollowUp } from "@/lib/api";

export const UNKNOWN = "__khong_ro__";
export type Selection = Record<string, { value: string; label: string }>;

/**
 * Câu hỏi phụ dạng nhóm radio, gửi mọi câu của một lượt cùng lúc (D-029).
 * Câu chưa chọn tính là "Không rõ". Sau khi gửi, `submitted` giữ lựa chọn để hiện lại ở chế độ chỉ đọc.
 */
export function FollowUpForm({
  questions,
  active,
  submitted,
  onSubmit,
}: {
  questions: FollowUp[];
  active: boolean;
  submitted?: Selection;
  onSubmit: (selection: Selection) => void;
}) {
  const [picked, setPicked] = useState<Record<string, string>>({});
  const locked = !active || submitted !== undefined;

  function submit(e: FormEvent) {
    e.preventDefault();
    if (locked) return;
    const selection: Selection = {};
    for (const q of questions) {
      const value = picked[q.dimension] ?? UNKNOWN;
      const option = q.options.find((o) => o.value === value);
      selection[q.dimension] = { value, label: option?.label ?? "Không rõ" };
    }
    onSubmit(selection);
  }

  return (
    <form onSubmit={submit} className="space-y-6 rounded-brutal border-3 border-ink bg-surface p-4 shadow-brutal">
      {questions.map((q) => {
        const current = submitted?.[q.dimension]?.value ?? picked[q.dimension];
        return (
          <fieldset key={q.dimension} disabled={locked}>
            <legend className="label mb-2">{q.question}</legend>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 xl:grid-cols-4">
              {q.options.map((o) => (
                <label
                  key={o.value}
                  className={`flex min-h-11 cursor-pointer items-center gap-2 rounded-brutal border-3 border-ink px-3 py-2 font-bold
                    has-[:checked]:bg-yellow has-[:focus-visible]:outline has-[:focus-visible]:outline-2
                    has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-ink
                    has-[:disabled]:cursor-default has-[:disabled:not(:checked)]:opacity-60
                    ${o.value === UNKNOWN ? "bg-paper font-medium" : "bg-surface"}`}
                >
                  <input
                    type="radio"
                    name={`${q.dimension}`}
                    value={o.value}
                    checked={current === o.value}
                    onChange={() => setPicked((p) => ({ ...p, [q.dimension]: o.value }))}
                    className="size-5 shrink-0 accent-ink"
                  />
                  <span>{o.label}</span>
                </label>
              ))}
            </div>
          </fieldset>
        );
      })}
      {submitted === undefined ? (
        <div className="flex flex-wrap items-center justify-end gap-4">
          <p className="text-sm text-muted">Câu chưa chọn được tính là “Không rõ”.</p>
          <Button type="submit" disabled={!active}>
            XEM MỨC PHẠT <ArrowRight size={20} aria-hidden />
          </Button>
        </div>
      ) : null}
    </form>
  );
}
