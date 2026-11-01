import type { DocStatus } from "@/lib/api";

const STATUS: Record<DocStatus, { text: string; tone: string }> = {
  con_hieu_luc: { text: "Còn hiệu lực", tone: "bg-green" },
  het_hieu_luc: { text: "Hết hiệu lực", tone: "bg-red" },
  het_hieu_luc_mot_phan: { text: "Hết hiệu lực một phần", tone: "bg-orange" },
  chua_co_hieu_luc: { text: "Chưa có hiệu lực", tone: "bg-surface" },
  unknown: { text: "Chưa rõ hiệu lực", tone: "bg-surface" },
};

export function StatusBadge({ status }: { status: DocStatus | null }) {
  const { text, tone } = STATUS[status ?? "unknown"];
  return <span className={`label inline-block rounded-brutal border-2 border-ink px-2 py-1 ${tone}`}>{text}</span>;
}
