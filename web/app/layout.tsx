import type { Metadata, Viewport } from "next";
import { Be_Vietnam_Pro, JetBrains_Mono } from "next/font/google";
import { AsOfProvider } from "@/components/AsOfContext";
import { Header } from "@/components/Header";
import "./globals.css";

const sans = Be_Vietnam_Pro({
  subsets: ["latin", "vietnamese"],
  weight: ["400", "500", "700", "800", "900"],
  variable: "--font-sans",
});
const mono = JetBrains_Mono({
  subsets: ["latin", "vietnamese"],
  weight: ["500", "700", "800"],
  variable: "--font-mono",
});

export const metadata: Metadata = {
  title: "LuậtGT",
  description: "Tra cứu luật giao thông đường bộ có trích dẫn điều khoản",
};
export const viewport: Viewport = { width: "device-width", initialScale: 1 };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    // suppressHydrationWarning: tiện ích trình duyệt (Grammarly, Bitdefender, trình quản lý mật khẩu…) hay gắn thêm
    // thuộc tính vào <html>/<body> trước khi React hydrate. Chỉ bỏ qua thuộc tính của đúng hai thẻ này, không lan xuống con.
    <html lang="vi" className={`${sans.variable} ${mono.variable}`} suppressHydrationWarning>
      <body className="flex min-h-dvh flex-col" suppressHydrationWarning>
        <AsOfProvider>
          <Header />
          {children}
        </AsOfProvider>
      </body>
    </html>
  );
}
