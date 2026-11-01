import type { Metadata } from "next";
import Link from "next/link";
import { StatusBadge } from "@/components/ui/Badge";
import { FilterChip } from "@/components/ui/Chip";
import { serverGet, type DocumentSummary } from "@/lib/api";
import { formatDate } from "@/lib/format";

export const metadata: Metadata = { title: "Văn bản · LuậtGT" };

const FILTERS = [
  { value: "", label: "Tất cả" },
  { value: "con_hieu_luc", label: "Còn hiệu lực" },
  { value: "het_hieu_luc_mot_phan", label: "Hết hiệu lực một phần" },
  { value: "het_hieu_luc", label: "Hết hiệu lực" },
  { value: "chua_co_hieu_luc", label: "Chưa có hiệu lực" },
];

export default async function DocumentsPage({ searchParams }: { searchParams: Promise<{ tinh_trang?: string }> }) {
  const { tinh_trang: status = "" } = await searchParams;
  const query = status ? `?tinh_trang=${encodeURIComponent(status)}` : "";
  const docs = (await serverGet<DocumentSummary[]>(`/api/documents${query}`)) ?? [];

  return (
    <main className="mx-auto w-full max-w-6xl space-y-6 px-4 py-6">
      <h1 className="text-4xl font-black leading-tight">Văn bản</h1>
      <nav aria-label="Lọc theo tình trạng hiệu lực" className="flex flex-wrap gap-2">
        {FILTERS.map((f) => (
          <FilterChip key={f.value} href={f.value ? `/van-ban?tinh_trang=${f.value}` : "/van-ban"} active={status === f.value}>
            {f.label}
          </FilterChip>
        ))}
      </nav>
      {docs.length === 0 ? <p className="text-muted">Không có văn bản nào ở tình trạng này.</p> : null}
      <ul className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
        {docs.map((d) => (
          <li key={d.vbpl_id}>
            <Link href={`/van-ban/${d.vbpl_id}`}
              className="brutal-press flex h-full flex-col gap-2 rounded-brutal border-3 border-ink bg-surface p-4 shadow-brutal">
              <span className="font-mono font-bold">{d.so_hieu}</span>
              <span className="flex-1 font-medium">{d.ten_van_ban}</span>
              <span><StatusBadge status={d.tinh_trang_norm} /></span>
              <span className="text-sm text-muted">
                Ban hành <span className="font-mono">{formatDate(d.ngay_ban_hanh)}</span> · Hiệu lực{" "}
                <span className="font-mono">{formatDate(d.ngay_hieu_luc)}</span>
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </main>
  );
}
