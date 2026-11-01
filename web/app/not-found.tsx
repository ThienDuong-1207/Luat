import Link from "next/link";

export default function NotFound() {
  return (
    <main className="mx-auto max-w-chat space-y-4 px-4 py-12">
      <h1 className="text-3xl font-black">Không tìm thấy trang</h1>
      <Link href="/van-ban" className="font-bold underline">Về danh sách văn bản</Link>
    </main>
  );
}
