"use client";

import { diffWords } from "diff";
import { ExternalLink, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { StatusBadge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Panel } from "@/components/ui/Panel";
import { getProvision, type DocStatus, type ProvisionDetail, type ProvisionVersion } from "@/lib/api";
import { formatDate } from "@/lib/format";

function Period({ v }: { v: ProvisionVersion }) {
  return (
    <span className="font-mono text-sm">
      {formatDate(v.valid_from)} – {formatDate(v.valid_to)}
    </span>
  );
}

function VersionDiff({ before, after }: { before: ProvisionVersion; after: ProvisionVersion }) {
  const parts = diffWords(before.text ?? "", after.text ?? "");
  return (
    <div className="grid gap-4">
      <section aria-label={`Bản ${before.version_no}, trước khi sửa`}>
        <p className="label mb-1">
          Trước · bản {before.version_no} · <Period v={before} />
        </p>
        <p className="legal whitespace-pre-line rounded-brutal border-2 border-ink p-2 text-sm">
          {before.text === null ? "Không có nội dung (đã bãi bỏ)." : null}
          {parts.filter((p) => !p.added).map((p, i) =>
            p.removed ? <del key={i} className="bg-red-soft">{p.value}</del> : <span key={i}>{p.value}</span>,
          )}
        </p>
      </section>
      <section aria-label={`Bản ${after.version_no}, sau khi sửa`}>
        <p className="label mb-1">
          Sau · bản {after.version_no} · <Period v={after} />
          {after.source_so_hieu ? ` · theo ${after.source_so_hieu}` : ""}
        </p>
        <p className="legal whitespace-pre-line rounded-brutal border-2 border-ink p-2 text-sm">
          {after.text === null ? "Điều khoản bị bãi bỏ từ phiên bản này." : null}
          {parts.filter((p) => !p.removed).map((p, i) =>
            p.added ? <ins key={i} className="bg-green-soft no-underline">{p.value}</ins> : <span key={i}>{p.value}</span>,
          )}
        </p>
      </section>
    </div>
  );
}

function Compare({ versions }: { versions: ProvisionVersion[] }) {
  const [index, setIndex] = useState(versions.length - 1);
  return (
    <div className="mt-4 space-y-4">
      {versions.length > 2 ? (
        <div role="group" aria-label="Chọn phiên bản để so sánh" className="flex flex-wrap gap-2">
          {versions.slice(1).map((v, i) => (
            <Button
              key={v.version_no}
              variant={index === i + 1 ? "primary" : "secondary"}
              aria-pressed={index === i + 1}
              onClick={() => setIndex(i + 1)}
              className="text-sm shadow-brutal-sm"
            >
              Bản {v.version_no}
            </Button>
          ))}
        </div>
      ) : null}
      <VersionDiff before={versions[index - 1]} after={versions[index]} />
    </div>
  );
}

/** Hiệu lực của chính điều khoản tại `as_of`, không phải của cả văn bản. */
function provisionStatus({ current, versions, as_of }: ProvisionDetail): DocStatus {
  if (current?.text) return "con_hieu_luc";
  return as_of < versions[0].valid_from ? "chua_co_hieu_luc" : "het_hieu_luc";
}

function Detail({ data }: { data: ProvisionDetail }) {
  const [comparing, setComparing] = useState(false);
  const { current, versions, document: doc } = data;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <StatusBadge status={provisionStatus(data)} />
        {doc ? <span className="font-mono text-sm">{doc.so_hieu}</span> : null}
      </div>
      {current ? (
        <>
          <p className="label text-muted">
            Áp dụng tại {formatDate(data.as_of)}: <Period v={current} />
          </p>
          <p className="legal whitespace-pre-line">{current.text ?? "Điều khoản đã bị bãi bỏ từ phiên bản này."}</p>
        </>
      ) : (
        <p className="legal">Điều khoản không có hiệu lực tại ngày {formatDate(data.as_of)}.</p>
      )}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-t-2 border-ink pt-4 text-sm">
        {doc?.source_url ? (
          <a href={doc.source_url} target="_blank" rel="noreferrer" className="inline-flex min-h-11 items-center gap-1 font-bold underline">
            Xem trên vbpl.vn <ExternalLink size={16} aria-hidden />
          </a>
        ) : null}
        {doc?.pdf_page ? <span className="font-mono">PDF trang {doc.pdf_page}</span> : null}
      </div>
      {versions.length > 1 ? (
        <Button variant="secondary" aria-expanded={comparing} onClick={() => setComparing((v) => !v)}>
          {comparing ? "Ẩn so sánh" : "So sánh phiên bản"}
        </Button>
      ) : (
        <p className="text-sm text-muted">Điều khoản này chỉ có một phiên bản.</p>
      )}
      {comparing ? <Compare versions={versions} /> : null}
    </div>
  );
}

function useProvision(provisionKey: string, asOf: string) {
  const [data, setData] = useState<ProvisionDetail | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let stale = false;
    setData(null);
    setFailed(false);
    getProvision(provisionKey, asOf)
      .then((d) => !stale && setData(d))
      .catch(() => !stale && setFailed(true));
    return () => {
      stale = true;
    };
  }, [provisionKey, asOf]);
  return { data, failed };
}

function Body({ data, failed }: { data: ProvisionDetail | null; failed: boolean }) {
  return (
    <>
      {failed ? <p role="alert">Không tải được nội dung điều khoản. Hãy thử lại.</p> : null}
      {!failed && !data ? <p role="status" className="text-muted">Đang tải nguyên văn…</p> : null}
      {data ? <Detail data={data} /> : null}
    </>
  );
}

type Props = { provisionKey: string; title: string; asOf: string; onClose: () => void };

/** Panel bật lên (modal): dùng trên màn hẹp và ở trang văn bản. */
export function ProvisionPanel({ provisionKey, title, asOf, onClose }: Props) {
  const { data, failed } = useProvision(provisionKey, asOf);
  return (
    <Panel title={data?.label ?? title} onClose={onClose}>
      <Body data={data} failed={failed} />
    </Panel>
  );
}

/** Nội dung cột tham chiếu cố định bên phải trang hỏi đáp (màn ≥ 1280px). */
export function ProvisionAside({ provisionKey, title, asOf, onClose }: Props) {
  const { data, failed } = useProvision(provisionKey, asOf);
  const headingRef = useRef<HTMLHeadingElement>(null);

  // Bấm chip khác thì đưa focus sang cột tham chiếu, người dùng bàn phím biết nội dung đã đổi
  useEffect(() => headingRef.current?.focus(), [provisionKey, asOf]);

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between gap-2 border-b-3 border-ink bg-yellow p-4">
        <h2 ref={headingRef} tabIndex={-1} className="font-extrabold leading-tight outline-none">
          {data?.label ?? title}
        </h2>
        <Button variant="secondary" aria-label="Đóng tham chiếu" onClick={onClose} className="shrink-0 px-0 shadow-brutal-sm">
          <X size={20} aria-hidden />
        </Button>
      </div>
      <div className="flex-1 overflow-y-auto p-4">
        <Body data={data} failed={failed} />
      </div>
    </div>
  );
}
