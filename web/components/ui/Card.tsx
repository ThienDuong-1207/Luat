import type { HTMLAttributes } from "react";

export function Card({ className = "", ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={`rounded-brutal border-3 border-ink bg-surface shadow-brutal ${className}`} {...props} />;
}
