import type { InputHTMLAttributes } from "react";

export function Input({ className = "", ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={`min-h-11 min-w-0 rounded-brutal border-3 border-ink bg-surface px-3 text-ink placeholder:text-muted ${className}`}
      {...props}
    />
  );
}
