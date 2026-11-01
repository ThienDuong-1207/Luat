export type Option = { value: string; label: string };
export type FollowUp = { dimension: string; question: string; options: Option[] };

export type Fact = {
  hanh_vi: string;
  phuong_tien: string[];
  doi_tuong: string | null;
  muc_phat_min: number | null;
  muc_phat_max: number | null;
  tru_diem_gplx: number | null;
  tuoc_gplx: string | null;
  bien_phap_bo_sung: string[];
  citation_ids: string[];
};

export type Citation = {
  id: string;
  provision_key: string;
  version_no: number;
  label: string;
  valid_from: string;
  source_url: string | null;
  pdf_page: number | null;
};

export type AskResponse = {
  session_id: string | null;
  status: "answered" | "need_clarification" | "not_found";
  answer_markdown: string;
  facts: Fact[];
  citations: Citation[];
  follow_up_questions: FollowUp[];
  related_questions: string[];
  as_of_date: string;
  disclaimer: string;
};

export type DocStatus = "con_hieu_luc" | "het_hieu_luc" | "het_hieu_luc_mot_phan" | "chua_co_hieu_luc" | "unknown";

export type DocumentSummary = {
  vbpl_id: string;
  so_hieu: string;
  ten_van_ban: string;
  loai_van_ban: string | null;
  tinh_trang: string | null;
  tinh_trang_norm: DocStatus | null;
  ngay_ban_hanh: string | null;
  ngay_hieu_luc: string | null;
  ngay_het_hieu_luc: string | null;
};

export type DocumentDetail = DocumentSummary & {
  co_quan_ban_hanh: string | null;
  nguoi_ky: string | null;
  source_url: string;
  relations: { relation_type: string; dst_so_hieu: string; dst_vbpl_id: string | null; ngay_hieu_luc: string | null }[];
  incoming: { relation_type: string; src_so_hieu: string; src_vbpl_id: string; ngay_hieu_luc: string | null }[];
};

export type ProvisionNode = {
  provision_id: string;
  provision_key: string;
  level: "phan" | "chuong" | "muc" | "dieu" | "khoan" | "diem";
  number: string;
  title: string | null;
  parent_id: string | null;
  text: string | null;
  n_versions: number;
};

export type AddedProvision = { provision_key: string; label: string; text: string; valid_from: string };

export type ProvisionTree = { as_of: string; provisions: ProvisionNode[]; added: AddedProvision[] };

export type ProvisionVersion = {
  version_no: number;
  text: string | null;
  source_so_hieu: string | null;
  valid_from: string;
  valid_to: string;
};

export type ProvisionDetail = {
  provision_key: string;
  label: string;
  as_of: string;
  document: {
    vbpl_id: string;
    so_hieu: string;
    source_url: string;
    tinh_trang_norm: DocStatus | null;
    pdf_page: number | null;
  } | null;
  current: ProvisionVersion | null;
  versions: ProvisionVersion[];
};

/** Gọi API từ trình duyệt qua rewrite cùng origin. */
export async function postJson<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(path, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

export async function getProvision(key: string, asOf: string): Promise<ProvisionDetail> {
  const query = asOf ? `?as_of=${asOf}` : "";
  const res = await fetch(`/api/provisions/${key}${query}`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

/** Gọi API từ server component: luôn lấy dữ liệu mới, trả null khi 404. */
export async function serverGet<T>(path: string): Promise<T | null> {
  const res = await fetch(`${process.env.API_URL ?? "http://localhost:8000"}${path}`, { cache: "no-store" });
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`API ${path}: HTTP ${res.status}`);
  return res.json();
}
