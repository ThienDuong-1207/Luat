"use client";

import { Button } from "@/components/ui/Button";

export default function ErrorPage({ reset }: { reset: () => void }) {
  return (
    <main className="mx-auto max-w-chat space-y-4 px-4 py-12">
      <h1 className="text-3xl font-black">Chưa tải được dữ liệu</h1>
      <p className="text-muted">Máy chủ API không phản hồi. Hãy thử lại sau ít phút.</p>
      <Button onClick={reset}>Thử lại</Button>
    </main>
  );
}
