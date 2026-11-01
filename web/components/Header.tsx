"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useAsOf } from "@/components/AsOfContext";
import { Input } from "@/components/ui/Input";

const NAV_LINK = "inline-flex min-h-11 items-center px-2 font-extrabold underline-offset-4 hover:underline";

export function Header() {
  const pathname = usePathname();
  const { asOf, setAsOf } = useAsOf();
  return (
    <header className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b-3 border-ink bg-paper px-4 py-2">
      <Link href="/" className="inline-flex min-h-11 items-center gap-2 text-xl font-black tracking-tight">
        LUẬTGT
        <span aria-hidden className="size-3 bg-ink" />
      </Link>
      <nav aria-label="Điều hướng chính" className="ml-auto flex items-center gap-2">
        <Link href="/van-ban" className={NAV_LINK}>
          Văn bản
        </Link>
        <Link href="/dashboard" className={NAV_LINK}>
          Dashboard
        </Link>
      </nav>
      {pathname === "/" ? (
        <label className="flex items-center gap-2">
          <span className="label">Ngày áp dụng</span>
          <Input type="date" value={asOf} onChange={(e) => setAsOf(e.target.value)} className="font-mono text-sm" />
        </label>
      ) : null}
    </header>
  );
}
