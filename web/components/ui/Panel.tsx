"use client";

import { X } from "lucide-react";
import { useEffect, useRef, type ReactNode } from "react";
import { Button } from "@/components/ui/Button";

/** Panel phải (desktop) / bottom sheet (mobile). `<dialog>` lo khoá focus và phím Esc. */
export function Panel({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    const dialog = ref.current;
    dialog?.showModal();
    return () => {
      dialog?.close();
      opener?.focus();
    };
  }, []);

  return (
    <dialog
      ref={ref}
      aria-label={title}
      className="panel"
      onCancel={onClose}
      onClick={(e) => e.target === ref.current && onClose()}
    >
      <div className="flex h-full flex-col">
        <div className="flex items-center justify-between gap-4 border-b-3 border-ink bg-yellow p-4">
          <h2 className="font-extrabold leading-tight">{title}</h2>
          <Button variant="secondary" aria-label="Đóng" onClick={onClose} className="shrink-0 px-0 shadow-brutal-sm">
            <X size={20} aria-hidden />
          </Button>
        </div>
        <div className="flex-1 overflow-y-auto p-4">{children}</div>
      </div>
    </dialog>
  );
}
