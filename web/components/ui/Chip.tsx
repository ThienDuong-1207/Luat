import Link from "next/link";
import type { ButtonHTMLAttributes, ComponentProps } from "react";

const BASE =
  "brutal-press inline-flex min-h-11 items-center rounded-brutal border-2 border-ink px-3 text-left text-sm shadow-brutal-sm";

/** Chip lựa chọn của câu hỏi phụ; `neutral` cho "Không rõ". */
export function Chip({
  neutral = false,
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { neutral?: boolean }) {
  const tone = neutral ? "bg-surface" : "bg-pink";
  return <button type="button" className={`${BASE} font-bold ${tone} ${className}`} {...props} />;
}

export function CitationChip({ className = "", ...props }: ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      type="button"
      className={`${BASE} mx-0.5 bg-blue align-middle font-mono font-bold ${className}`}
      {...props}
    />
  );
}

export function FilterChip({ active, ...props }: ComponentProps<typeof Link> & { active: boolean }) {
  const tone = active ? "bg-ink text-surface" : "bg-surface";
  return <Link aria-current={active ? "true" : undefined} className={`${BASE} font-bold ${tone}`} {...props} />;
}
