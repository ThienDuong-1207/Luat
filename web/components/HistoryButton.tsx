"use client";

import { History } from "lucide-react";
import { useState } from "react";
import { ProvisionPanel } from "@/components/ProvisionPanel";
import { Button } from "@/components/ui/Button";

export function HistoryButton({ provisionKey, title, asOf, count }: { provisionKey: string; title: string; asOf: string; count: number }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button variant="secondary" onClick={() => setOpen(true)} aria-label={`Lịch sử ${count} phiên bản của ${title}`}
        className="text-sm shadow-brutal-sm">
        <History size={16} aria-hidden /> {count} phiên bản
      </Button>
      {open ? <ProvisionPanel provisionKey={provisionKey} title={title} asOf={asOf} onClose={() => setOpen(false)} /> : null}
    </>
  );
}
