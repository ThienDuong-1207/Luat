import type { Citation, Fact } from "@/lib/api";

const OPEN_END = "9999-12-31";

const VEHICLES: Record<string, string> = {
  o_to: "Ô tô",
  xe_4_banh_dong_co: "Xe bốn bánh có gắn động cơ",
  xe_may: "Xe máy",
  xe_dap: "Xe đạp",
  xe_tho_so: "Xe thô sơ",
  xe_may_chuyen_dung: "Xe máy chuyên dùng",
  may_keo: "Máy kéo",
  co_gioi: "Xe cơ giới",
  nguoi_di_bo: "Người đi bộ",
  hanh_khach: "Hành khách",
};

export function vehicleLabels(values: string[]): string {
  return values.flatMap((v) => VEHICLES[v] ?? []).join(", ") || "Mọi phương tiện";
}

/** "2026-07-01" → "01/07/2026"; không qua Date để tránh lệch múi giờ. */
export function formatDate(iso: string | null): string {
  if (!iso) return "—";
  if (iso === OPEN_END) return "nay";
  const [y, m, d] = iso.split("-");
  return `${d}/${m}/${y}`;
}

export function todayVn(): string {
  return new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Ho_Chi_Minh" });
}

export function money(n: number): string {
  return n.toLocaleString("de-DE");
}

export function fineRange(f: Fact): string {
  if (f.muc_phat_min == null && f.muc_phat_max == null) return "—";
  if (f.muc_phat_min === f.muc_phat_max || f.muc_phat_max == null) return `${money(f.muc_phat_min!)} đ`;
  if (f.muc_phat_min == null) return `đến ${money(f.muc_phat_max)} đ`;
  return `${money(f.muc_phat_min)}–${money(f.muc_phat_max)} đ`;
}

/** Nhãn gọn cho chip: "Đ.7 K.9 d) NĐ 168/2024". */
export function citationChipLabel(c: Pick<Citation, "provision_key" | "label">): string {
  const parts = Object.fromEntries(c.provision_key.split("/").slice(1).map((p) => [p[0], p.slice(1)]));
  const doc = c.label.match(/(NĐ|Luật) (\d+\/\d{4})/);
  if (!parts.D || !doc) return c.label;
  const point = parts.P && (parts.P === "dd" ? "đ" : parts.P);
  return [`Đ.${parts.D}`, parts.K && `K.${parts.K}`, point && `${point})`, `${doc[1]} ${doc[2]}`]
    .filter(Boolean)
    .join(" ");
}

/** `[c1]` thành link để renderer đổi thành chip; dòng "Căn cứ:" đã có hàng chip riêng. */
export const FINE_HREF = "#muc-phat";
// Số tiền ("400.000–600.000 đồng", "từ 400.000 đồng đến 600.000 đồng"), trừ điểm, tước GPLX: tô vàng (D-029)
const RE_FINE = new RegExp(
  [
    String.raw`(?:từ\s+)?\d{1,3}(?:\.\d{3})+(?:\s*đồng)?\s*(?:–|-|đến)\s*\d{1,3}(?:\.\d{3})+\s*đồng`,
    String.raw`\d{1,3}(?:\.\d{3})+\s*đồng`,
    String.raw`trừ\s+\d+\s+điểm(?:\s+GPLX|\s+giấy phép lái xe)?`,
    String.raw`tước\s+(?:quyền sử dụng\s+)?(?:GPLX|giấy phép lái xe)\s+(?:từ\s+)?\d+\s*(?:–|-|đến)\s*\d+\s+tháng`,
  ].join("|"),
  "gi",
);

export function prepareAnswer(markdown: string): string {
  return markdown
    .split("\n")
    .filter((line) => !line.startsWith("Căn cứ:"))
    .join("\n")
    .replace(RE_FINE, (m) => `[${m}](${FINE_HREF})`)
    .replace(/\[(c\d+)\]/g, "[$1](#$1)")
    .trim();
}
