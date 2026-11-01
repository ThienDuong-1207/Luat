import type { ButtonHTMLAttributes } from "react";

type Props = ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" };

export function Button({ variant = "primary", className = "", ...props }: Props) {
  const tone = variant === "primary" ? "bg-yellow" : "bg-surface";
  return (
    <button
      type="button"
      className={`brutal-press inline-flex min-h-11 min-w-11 items-center justify-center gap-2 rounded-brutal border-3 border-ink px-4 font-extrabold shadow-brutal disabled:cursor-not-allowed disabled:opacity-60 ${tone} ${className}`}
      {...props}
    />
  );
}
