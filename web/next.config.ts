import type { NextConfig } from "next";

const apiUrl = process.env.API_URL ?? "http://localhost:8000";

const config: NextConfig = {
  // Trình duyệt chỉ gọi cùng origin, kể cả từ điện thoại trong mạng LAN
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${apiUrl}/api/:path*` }];
  },
  // Lần hỏi đầu phải nạp model embedding
  experimental: { proxyTimeout: 120_000 },
};

export default config;
