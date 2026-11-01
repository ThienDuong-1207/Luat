import type { ReactNode } from "react";

export type Column<T> = { header: string; cell: (row: T) => ReactNode; numeric?: boolean };

/** Bảng ở desktop, danh sách thẻ ở mobile (spec 15.3.5). */
export function Table<T>({ columns, rows, caption }: { columns: Column<T>[]; rows: T[]; caption: string }) {
  return (
    <>
      <table className="hidden w-full border-collapse border-3 border-ink text-sm md:table">
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr className="bg-yellow">
            {columns.map((c) => (
              <th key={c.header} scope="col" className={`label border-2 border-ink p-2 ${c.numeric ? "text-right" : "text-left"}`}>
                {c.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i}>
              {columns.map((c) => (
                <td key={c.header} className={`border-2 border-ink p-2 align-top ${c.numeric ? "text-right font-mono" : ""}`}>
                  {c.cell(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      <ul className="space-y-4 md:hidden" aria-label={caption}>
        {rows.map((row, i) => (
          <li key={i} className="rounded-brutal border-3 border-ink">
            <dl>
              {columns.map((c) => (
                <div key={c.header} className="border-b-2 border-ink p-2 last:border-b-0">
                  <dt className="label text-muted">{c.header}</dt>
                  <dd className={c.numeric ? "font-mono" : ""}>{c.cell(row)}</dd>
                </div>
              ))}
            </dl>
          </li>
        ))}
      </ul>
    </>
  );
}
