import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { ExternalLink } from "lucide-react";
import { HistoryButton } from "@/components/HistoryButton";
import { StatusBadge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";
import { serverGet, type DocumentDetail, type ProvisionNode, type ProvisionTree } from "@/lib/api";
import { formatDate, todayVn } from "@/lib/format";

type Params = { params: Promise<{ id: string }>; searchParams: Promise<{ as_of?: string }> };

const OUTGOING: Record<string, string> = {
  sua_doi: "Sửa đổi",
  bi_sua_doi: "Được sửa đổi bởi",
  thay_the: "Thay thế",
  bi_thay_the: "Được thay thế bởi",
  huong_dan: "Hướng dẫn",
  duoc_huong_dan: "Được hướng dẫn bởi",
  bai_bo: "Bãi bỏ",
};
const INCOMING: Record<string, string> = {
  sua_doi: "Được sửa đổi bởi",
  thay_the: "Được thay thế bởi",
  huong_dan: "Được hướng dẫn bởi",
  bai_bo: "Bị bãi bỏ bởi",
};
const HEADING: Record<string, string> = { phan: "Phần", chuong: "Chương", muc: "Mục" };

function timeline(doc: DocumentDetail) {
  const seen = new Set<string>();
  const items = [
    ...doc.incoming.filter((r) => INCOMING[r.relation_type]).map((r) => ({
      label: INCOMING[r.relation_type], soHieu: r.src_so_hieu, id: r.src_vbpl_id as string | null, date: r.ngay_hieu_luc,
    })),
    ...doc.relations.filter((r) => OUTGOING[r.relation_type]).map((r) => ({
      label: OUTGOING[r.relation_type], soHieu: r.dst_so_hieu, id: r.dst_vbpl_id, date: r.ngay_hieu_luc,
    })),
  ];
  return items
    .filter((i) => !seen.has(i.soHieu) && seen.add(i.soHieu))
    .toSorted((a, b) => (a.date ?? "9999").localeCompare(b.date ?? "9999"));
}

function ProvisionText({ node, asOf }: { node: ProvisionNode; asOf: string }) {
  const marker = node.level === "khoan" ? `${node.number}. ` : node.level === "diem" ? `${node.number === "dd" ? "đ" : node.number}) ` : "";
  const body = node.text ?? "Không có hiệu lực tại ngày này.";
  return (
    <div className={`${node.level === "diem" ? "pl-4" : ""} space-y-1`}>
      {node.text || node.level !== "dieu" ? (
        <p className={`legal whitespace-pre-line ${node.text ? "" : "text-muted"}`}>{marker}{body}</p>
      ) : null}
      {node.n_versions > 1 ? (
        <HistoryButton provisionKey={node.provision_key} title={`${node.level === "diem" ? "Điểm" : node.level === "khoan" ? "Khoản" : "Điều"} ${node.number}`} asOf={asOf} count={node.n_versions} />
      ) : null}
    </div>
  );
}

export async function generateMetadata({ params }: Params): Promise<Metadata> {
  const doc = await serverGet<DocumentDetail>(`/api/documents/${(await params).id}`);
  return { title: doc ? `${doc.so_hieu} · LuậtGT` : "LuậtGT" };
}

export default async function DocumentPage({ params, searchParams }: Params) {
  const { id } = await params;
  const asOf = (await searchParams).as_of || todayVn();
  const [doc, tree] = await Promise.all([
    serverGet<DocumentDetail>(`/api/documents/${id}`),
    serverGet<ProvisionTree>(`/api/documents/${id}/provisions?as_of=${encodeURIComponent(asOf)}`),
  ]);
  if (!doc || !tree) notFound();

  const toc = tree.provisions.filter((p) => ["phan", "chuong", "muc", "dieu"].includes(p.level));
  const events = timeline(doc);
  const list = (
    <ul className="space-y-1 text-sm">
      {toc.map((p) => (
        <li key={p.provision_id} className={p.level === "dieu" ? "" : "pt-2 font-extrabold"}>
          <a href={`#${encodeURIComponent(p.provision_id)}`} className="inline-block py-1 hover:underline">
            {p.level === "dieu" ? `Điều ${p.number}` : `${HEADING[p.level]} ${p.number}`}
            {p.title ? `. ${p.title}` : ""}
          </a>
        </li>
      ))}
    </ul>
  );

  return (
    <main className="mx-auto w-full max-w-6xl space-y-6 px-4 py-6">
      <Link href="/van-ban" className="inline-flex min-h-11 items-center font-bold underline">Danh sách văn bản</Link>
      <Card className="space-y-4 p-4">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-mono font-bold">{doc.so_hieu}</span>
          <StatusBadge status={doc.tinh_trang_norm} />
        </div>
        <h1 className="text-3xl font-black leading-tight md:text-4xl">{doc.ten_van_ban}</h1>
        <dl className="grid gap-2 text-sm sm:grid-cols-2 lg:grid-cols-4">
          {[
            ["Cơ quan ban hành", doc.co_quan_ban_hanh ?? "—"],
            ["Ngày ban hành", formatDate(doc.ngay_ban_hanh)],
            ["Ngày hiệu lực", formatDate(doc.ngay_hieu_luc)],
            ["Ngày hết hiệu lực", doc.ngay_het_hieu_luc ? formatDate(doc.ngay_het_hieu_luc) : "—"],
          ].map(([term, value]) => (
            <div key={term}>
              <dt className="label text-muted">{term}</dt>
              <dd className="font-medium">{value}</dd>
            </div>
          ))}
        </dl>
        <a href={doc.source_url} target="_blank" rel="noreferrer" className="inline-flex min-h-11 items-center gap-1 font-bold underline">
          Xem trên vbpl.vn <ExternalLink size={16} aria-hidden />
        </a>
      </Card>

      {events.length > 0 ? (
        <section aria-labelledby="quan-he">
          <h2 id="quan-he" className="mb-4 text-2xl font-black">Quan hệ sửa đổi</h2>
          <ol className="space-y-2 border-l-8 border-ink pl-4">
            {events.map((e) => (
              <li key={e.soHieu} className="rounded-brutal border-2 border-ink bg-surface p-2 text-sm">
                <span className="label mr-2">{e.label}</span>
                {e.id ? (
                  <Link href={`/van-ban/${e.id}`} className="font-mono font-bold underline">{e.soHieu}</Link>
                ) : (
                  <span className="font-mono">{e.soHieu}</span>
                )}
                {e.date ? <span className="ml-2 font-mono text-muted">{formatDate(e.date)}</span> : null}
              </li>
            ))}
          </ol>
        </section>
      ) : null}

      <form className="flex flex-wrap items-end gap-2">
        <label className="flex flex-col gap-1">
          <span className="label">Xem nội dung tại ngày</span>
          <Input type="date" name="as_of" defaultValue={asOf} className="font-mono text-sm" />
        </label>
        <Button type="submit" variant="secondary">Xem</Button>
      </form>

      <div className="gap-8 md:grid md:grid-cols-[280px_minmax(0,1fr)]">
        <details className="mb-6 rounded-brutal border-3 border-ink bg-surface p-2 md:hidden">
          <summary className="flex min-h-11 cursor-pointer items-center font-extrabold">Mục lục</summary>
          <nav aria-label="Mục lục">{list}</nav>
        </details>
        <nav aria-label="Mục lục" className="sticky top-4 hidden max-h-[calc(100dvh-2rem)] self-start overflow-y-auto rounded-brutal border-3 border-ink bg-surface p-4 md:block">
          {list}
        </nav>
        <article className="min-w-0 space-y-4 rounded-brutal border-3 border-ink bg-surface p-4">
          {tree.provisions.map((p) =>
            p.level === "dieu" ? (
              <div key={p.provision_id} id={encodeURIComponent(p.provision_id)} className="scroll-mt-4 space-y-2 pt-4">
                <h3 className="font-extrabold">Điều {p.number}.{p.title ? ` ${p.title}` : ""}</h3>
                <ProvisionText node={p} asOf={asOf} />
              </div>
            ) : p.level === "khoan" || p.level === "diem" ? (
              <ProvisionText key={p.provision_id} node={p} asOf={asOf} />
            ) : (
              <h2 key={p.provision_id} id={encodeURIComponent(p.provision_id)} className="scroll-mt-4 pt-6 text-center text-xl font-black">
                {HEADING[p.level]} {p.number}{p.title ? `: ${p.title}` : ""}
              </h2>
            ),
          )}
          {tree.added.length > 0 ? (
            <section className="space-y-2 border-t-3 border-ink pt-4">
              <h2 className="text-xl font-black">Điều khoản được bổ sung</h2>
              {tree.added.map((a) => (
                <div key={a.provision_key}>
                  <h3 className="font-extrabold">{a.label}</h3>
                  <p className="legal whitespace-pre-line">{a.text}</p>
                  <p className="text-sm text-muted">Áp dụng từ {formatDate(a.valid_from)}</p>
                </div>
              ))}
            </section>
          ) : null}
        </article>
      </div>
    </main>
  );
}
