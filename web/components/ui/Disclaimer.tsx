export function Disclaimer({ children }: { children: string }) {
  return (
    <p className="rounded-brutal border-2 border-dashed border-ink bg-paper p-2 text-[13px] leading-snug text-muted">
      {children}
    </p>
  );
}
