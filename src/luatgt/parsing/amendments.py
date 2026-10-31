"""Parse chỉ dẫn sửa đổi của văn bản sửa đổi (vd NĐ 238/2026) → bản ghi `amendments` (spec 8.4).

Đầu vào là các dòng `provisions` (Silver) của văn bản sửa đổi: mỗi Điều/Khoản/Điểm có câu chỉ dẫn ở đầu
(tiêu đề Điều, hoặc dòng đầu của Khoản/Điểm) và nội dung mới trong ngoặc kép ở các dòng sau.

Hỗ trợ (giai đoạn 1): sửa đổi, bổ sung (kể cả "vào trước/sau …"), bãi bỏ — mức Điều/Khoản/Điểm.
Câu làm ngữ cảnh ("Sửa đổi… một số điểm, khoản của Điều 6") cộng dồn xuống các chỉ dẫn con.
Văn bản đích xác định theo tên văn bản, hoặc theo từng Điều với văn bản sửa nhiều văn bản (D-017).
Sửa cụm từ (bổ sung, thay thế, bỏ) → bản ghi origin = phrase, áp vào text lúc dựng phiên bản (D-018).
Không hỗ trợ: đoạn, phụ lục, tên Điều → action = unsupported, parse_status = needs_review.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from luatgt.parsing.html_fulltext import SourceLine
from luatgt.parsing.structure import Node, doc_key, parse_structure

RE_VERB = re.compile(
    r"^(?:(?:\d+[a-z]?\.|[a-zđ]\d?\))\s+)?(Sửa đổi,?\s*bổ sung|Sửa đổi|Bổ sung|Bãi bỏ|Thay thế|Thay|Bỏ)\b",
    re.IGNORECASE,
)
RE_UNSUPPORTED = re.compile(r"cụm từ|\bđoạn\b|\bcâu\b|Thay thế|^(?:Thay|Bỏ)\b|\btên\s+Điều\b", re.IGNORECASE)
RE_MARKER = re.compile(r"^(?:\d+[a-z]?\.|[a-zđ]\d?\))\s+")
RE_REF = re.compile(
    r"(?P<kind>điểm|khoản|Điều)\s+(?P<val>\d+[a-z]?|[a-zđ]\d?)(?!\w)", re.IGNORECASE
)
# "điểm a, b, d và điểm đ" → "điểm a, điểm b, điểm d và điểm đ"; tương tự "khoản 9, 10"
RE_BARE_DIEM = re.compile(r"(điểm\s+[a-zđ]\d?)((?:\s*(?:,|và)\s*[a-zđ]\d?(?!\w))+)", re.IGNORECASE)
RE_BARE_KHOAN = re.compile(r"(khoản\s+\d+[a-z]?)((?:\s*(?:,|và)\s*\d+[a-z]?(?!\w))+)", re.IGNORECASE)
RE_TARGET_DOC = re.compile(
    r"(?:của|tại)\s+(?:Nghị định|Luật|Thông tư|Nghị quyết|Quyết định)\s+số\s+(\d+/\d{4}/[A-ZĐ0-9-]+)"
)
RE_DOC_REF = re.compile(r"(?:Nghị định|Luật|Thông tư|Nghị quyết|Quyết định)\s+số:?\s+(\d+/\d{4}/[A-ZĐ0-9-]+)")
RE_TARGET_LAW_NAME = re.compile(r"của\s+(Luật\s.+?)\s*$")
RE_MIXED_ADD = re.compile(r"\bvà\s+bổ\s+sung\s+(.+)", re.IGNORECASE)
RE_WHOLE_DOC = re.compile(r"^(?:Nghị định|Luật|Thông tư|Nghị quyết|Quyết định)\s+này\b")
_Q = r"""[“"]([^”"]+)[”"]"""
RE_PHRASE_CLAUSE = re.compile(
    rf"(?:cụm\s+)?từ\s*{_Q}"
    rf"(?:\s*bằng\s+(?:cụm\s+)?từ\s*{_Q}|\s*(?:vào\s+)?(sau|trước)\s+(?:cụm\s+)?từ\s*{_Q})?"
)
RE_OPEN_QUOTE = re.compile(r'^\s*["“„]')
RE_CLOSE_QUOTE = re.compile(r'["”]\s*[.;,]?\s*$')
RE_DATE = re.compile(r"ngày\s+(\d{1,2})\s+tháng\s+(\d{1,2})\s+năm\s+(\d{4})")


@dataclass(frozen=True)
class Ref:
    dieu: str | None = None
    khoan: str | None = None
    diem: str | None = None

    def merged(self, ctx: Ref) -> Ref:
        """Điền cấp còn thiếu từ ngữ cảnh. Điểm không lấy khoản ngữ cảnh nếu đã có Điều riêng."""
        if self.dieu is not None:
            return self
        khoan = self.khoan
        if khoan is None and self.diem is not None:
            khoan = ctx.khoan
        return Ref(ctx.dieu, khoan, self.diem)

    @property
    def level(self) -> str:
        return "diem" if self.diem else "khoan" if self.khoan else "dieu"

    def key(self, dkey: str) -> str:
        parts = [f"D{self.dieu}"]
        if self.khoan:
            parts.append(f"K{self.khoan}")
        if self.diem:
            parts.append("P" + ("dd" if self.diem == "đ" else self.diem))
        return f"{dkey}/" + "/".join(parts)


@dataclass
class Amendment:
    amendment_id: str
    amending_vbpl_id: str
    target_so_hieu: str
    target_key: str
    action: str  # sua_doi | bo_sung | bai_bo | unsupported
    new_text: str | None
    effective_date: date | None
    raw_instruction: str
    parse_status: str  # ok | needs_review
    origin: str = "explicit"  # explicit | content_child | implied_by_replace
    review_reason: str | None = None
    level: str | None = None
    title: str | None = None  # tiêu đề Điều mới (khi thay cả Điều)
    phrase_op: str | None = None  # replace | remove | insert_after | insert_before
    phrase_old: str | None = None  # cụm bị thay/bỏ, hoặc cụm làm mốc khi chèn
    phrase_scope: str | None = None  # tree: cả mục con | own: chỉ dòng tên của mục


@dataclass
class _ProvNode:
    row: dict
    children: list[_ProvNode] = field(default_factory=list)

    @property
    def level(self) -> str:
        return self.row["level"]

    @property
    def lines(self) -> list[str]:
        return (self.row["text"] or "").split("\n") if self.row["text"] else []

    @property
    def header(self) -> str:
        if self.level == "dieu":
            return self.row["title"] or ""
        return self.lines[0] if self.lines else ""

    @property
    def content(self) -> list[str]:
        return self.lines if self.level == "dieu" else self.lines[1:]


def build_tree(rows: list[dict]) -> list[_ProvNode]:
    nodes = {r["provision_id"]: _ProvNode(r) for r in rows}
    roots = []
    for r in sorted(rows, key=lambda r: r["ordinal"]):
        n = nodes[r["provision_id"]]
        parent = nodes.get(r["parent_id"]) if r["parent_id"] else None
        (parent.children if parent else roots).append(n)
    return roots


def _expand_bare(s: str) -> str:
    s = RE_BARE_DIEM.sub(lambda m: m.group(1) + re.sub(r"([a-zđ]\d?)(?!\w)", r"điểm \1", m.group(2)), s)
    return RE_BARE_KHOAN.sub(lambda m: m.group(1) + re.sub(r"(\d+[a-z]?)", r"khoản \1", m.group(2)), s)


def parse_refs(text: str) -> list[Ref]:
    """"điểm l, điểm m khoản 5 Điều 20" → [Ref(20,5,l), Ref(20,5,m)]. Điều ở cuối áp cho cả nhóm."""
    targets: list[dict] = []
    pending: list[str] = []
    for m in RE_REF.finditer(_expand_bare(text)):
        kind, val = m.group("kind").lower(), m.group("val")
        if kind == "điểm":
            pending.append(val)
        elif kind == "khoản":
            if pending:
                targets += [{"diem": p, "khoan": val} for p in pending]
                pending = []
            else:
                targets.append({"khoan": val})
        else:  # Điều
            if pending:
                targets += [{"diem": p} for p in pending]
                pending = []
            open_targets = [t for t in targets if "dieu" not in t]
            for t in open_targets:
                t["dieu"] = val
            if not open_targets:
                targets.append({"dieu": val})
    targets += [{"diem": p} for p in pending]
    return [Ref(t.get("dieu"), t.get("khoan"), t.get("diem")) for t in targets]


def _strip_instruction(header: str) -> str:
    return RE_MARKER.sub("", header).strip()


def _verb(header: str) -> str | None:
    m = RE_VERB.match(header)
    if not m:
        return None
    v = m.group(1).lower()
    if v.startswith("sửa đổi"):
        return "sua_doi"
    return {"bổ sung": "bo_sung", "bãi bỏ": "bai_bo"}.get(v, "unsupported")


def _target_refs(header: str) -> tuple[list[Ref], Ref]:
    """(mục bị tác động, vị trí "vào trước/sau …" dùng để điền cấp còn thiếu)."""
    body = re.sub(r"\s*như sau:?\s*$", "", _strip_instruction(header).split("“")[0])
    m = re.search(r"\svào\s+(?:trước|sau)?\s*", body)
    what, where = (body[: m.start()], body[m.end():]) if m else (body, "")
    position = Ref()
    for r in parse_refs(where):
        position = Ref(r.dieu or position.dieu, r.khoan or position.khoan, None)
    return parse_refs(what), position


@dataclass(frozen=True)
class PhraseEdit:
    op: str
    old: str
    new: str | None
    refs: tuple[Ref, ...]
    scope: str = "tree"


def parse_phrase_edits(header: str) -> list[PhraseEdit] | None:
    """Câu sửa cụm từ → các thao tác, mỗi thao tác kèm mục áp dụng. None nếu không đúng mẫu.

    Một câu có thể nhiều vế: "Bỏ cụm từ A tại X, cụm từ B tại Y"; "tại Z" ở cuối áp cho các vế chưa có nơi.
    """
    body = _strip_instruction(header)
    low = body.lower()
    kind = ("replace" if low.startswith("thay") else "insert" if low.startswith("bổ sung")
            else "remove" if low.startswith(("bỏ", "bãi bỏ")) else None)
    clauses = list(RE_PHRASE_CLAUSE.finditer(body))
    if kind is None or not clauses:
        return None
    out: list[PhraseEdit] = []
    pending: list[tuple[str, str, str | None]] = []
    for i, m in enumerate(clauses):
        first, by, pos, anchor = m.groups()
        if kind == "replace" and by:
            pending.append(("replace", first, by))
        elif kind == "remove" and not (by or pos):
            pending.append(("remove", first, None))
        elif kind == "insert" and pos:
            pending.append(("insert_after" if pos == "sau" else "insert_before", anchor, first))
        else:
            return None
        tail = body[m.end(): clauses[i + 1].start() if i + 1 < len(clauses) else len(body)]
        where = re.search(r"\btại\s+(tên\s+)?(.+)", tail, re.DOTALL)
        if where:
            refs = tuple(parse_refs(where.group(2)))
            if not refs:
                return None
            scope = "own" if where.group(1) else "tree"
            out += [PhraseEdit(op, old, new, refs, scope) for op, old, new in pending]
            pending = []
    return out if out and not pending else None


def _target_text(header: str) -> str:
    """Phần nêu mục bị tác động, bỏ vị trí "vào trước/sau …"."""
    return re.split(r"\svào\s+(?:trước|sau)?", header.split("“")[0], maxsplit=1)[0]


def _strip_quotes(lines: list[str]) -> list[str]:
    out = list(lines)
    if out:
        out[0] = RE_OPEN_QUOTE.sub("", out[0], count=1)
        out[-1] = RE_CLOSE_QUOTE.sub("", out[-1])
        if out[-1] and not out[-1].endswith((".", ";", ":", ",")):
            out[-1] += "."
    return [ln for ln in out if ln.strip()]


def _parse_content(lines: list[str], target: Ref, target_so_hieu: str) -> dict[str, Node]:
    """Nội dung mới → node theo khoá của văn bản bị sửa. Thêm dòng giả để đặt đúng cấp."""
    body = _strip_quotes(lines)
    prefix: list[str] = []
    if target.level != "dieu" or not (body and body[0].startswith("Điều ")):
        prefix.append(f"Điều {target.dieu}. __ctx__")
    if target.level == "diem" and target.khoan:
        prefix.append(f"{target.khoan}. __ctx__")
    parsed = parse_structure([SourceLine(t) for t in prefix + body], target_so_hieu)
    return {n.key: n for n in parsed.nodes()}


@dataclass
class EffectiveSchedule:
    """Ngày riêng trong Điều hiệu lực. Khoá là đường dẫn trong văn bản sửa đổi, vd "D7/K20/Pa"."""

    exact: dict[str, date] = field(default_factory=dict)  # "Quy định tại điểm a khoản 20 Điều 7 có hiệu lực…"
    partial: dict[str, date] = field(default_factory=dict)  # chỉ một phần nội dung của mục có ngày riêng
    unresolved: list[date] = field(default_factory=list)  # không xác định được mục

    def lookup(self, table: dict[str, date], path: str) -> date | None:
        return next((d for k, d in table.items() if f"/{k}/" in f"/{path}/"), None)


def _is_effective_article(title: str) -> bool:
    t = title.lower()
    return "hiệu lực" in t or t.startswith("điều khoản thi hành")


def effective_schedule(rows: list[dict], eff: date | None) -> EffectiveSchedule:
    """Đọc Điều hiệu lực, giữ các ngày khác ngày hiệu lực chung `eff`. Câu "hết hiệu lực" không tính."""
    out = EffectiveSchedule()
    for r in rows:
        if r["level"] != "dieu" or not _is_effective_article(r["title"] or ""):
            continue
        prefix = r["provision_id"].split(":", 1)[1] + "/"
        texts = [r["text"] or ""] + [
            c["text"] or "" for c in rows if c["provision_id"].split(":", 1)[1].startswith(prefix)
        ]
        for line in (ln for t in texts for ln in t.split("\n")):
            line = RE_MARKER.sub("", line.strip())
            m = RE_DATE.search(line)
            if not m or "có hiệu lực" not in line:
                continue
            when = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
            if when == eff or RE_WHOLE_DOC.match(line):
                if when != eff:
                    out.unresolved.append(when)
                continue
            head = line.split("có hiệu lực", 1)[0]
            refs = parse_refs(head.rsplit(" tại ", 1)[1]) if " tại " in head else []
            if not line.startswith("Quy định ") or not refs:
                out.unresolved.append(when)
                continue
            table = out.exact if line.startswith("Quy định tại ") else out.partial
            for ref in refs:
                table[ref.key("").lstrip("/")] = when
    return out


def parse_amendments(
    amending_doc: dict,
    amending_rows: list[dict],
    target_rows_by_so_hieu: dict[str, list[dict]],
    target_names: dict[str, str] | None = None,
) -> list[Amendment]:
    """Sinh bản ghi amendments cho một văn bản sửa đổi.

    amending_doc: dòng Silver `documents` (cần vbpl_id, ten_van_ban, ngay_hieu_luc).
    target_rows_by_so_hieu: provisions (Silver) của văn bản bị sửa, để kiểm tra khoá tồn tại.
        Văn bản đích không có ở đây (ngoài seed list) thì bỏ qua các Điều sửa nó.
    target_names: tên luật viết thường → số hiệu, cho Điều chỉ nêu tên ("… của Luật Đường bộ").
    """
    vid = amending_doc["vbpl_id"]
    m = RE_TARGET_DOC.search(amending_doc.get("ten_van_ban") or "")
    default_target = m.group(1) if m else None
    eff = amending_doc.get("ngay_hieu_luc")
    schedule = effective_schedule(amending_rows, eff)
    out: list[Amendment] = []

    def target_index(so_hieu: str) -> dict[str, dict]:
        return {r["provision_key"]: r for r in target_rows_by_so_hieu.get(so_hieu, [])}

    def emit(node: _ProvNode, idx: list[int], **kw) -> None:
        path = node.row["provision_id"].split(":", 1)[1]
        idx[0] += 1
        status = kw.pop("parse_status", "ok")
        reason = kw.pop("review_reason", None)
        partial = schedule.lookup(schedule.partial, path)
        if status == "ok" and (schedule.unresolved or partial):
            dates = schedule.unresolved or [partial]
            status, reason = "needs_review", f"ngày hiệu lực riêng: {dates}"
        out.append(Amendment(
            amendment_id=f"{vid}:{path}#{idx[0]}", amending_vbpl_id=vid,
            effective_date=schedule.lookup(schedule.exact, path) or eff,
            raw_instruction=node.header.strip(), parse_status=status, review_reason=reason, **kw,
        ))

    def leaf(node: _ProvNode, ctx: Ref, so_hieu: str) -> None:
        idx = [0]
        header = node.header
        verb = _verb(header)
        dkey = doc_key(so_hieu)
        existing = target_index(so_hieu)
        refs, position = _target_refs(header)
        refs = [r.merged(Ref(position.dieu or ctx.dieu, position.khoan or ctx.khoan)) for r in refs]
        refs = [r.merged(ctx) for r in refs]

        if verb == "unsupported" or RE_UNSUPPORTED.search(_strip_instruction(header)):
            edits = parse_phrase_edits(header)
            if edits:
                for e in edits:
                    for r in (x.merged(ctx) for x in e.refs):
                        ok = r.dieu is not None and r.key(dkey) in existing
                        emit(node, idx, target_so_hieu=so_hieu, target_key=r.key(dkey) if r.dieu else "",
                             action="sua_doi", new_text=e.new, level=r.level, origin="phrase",
                             phrase_op=e.op, phrase_old=e.old, phrase_scope=e.scope,
                             parse_status="ok" if ok else "needs_review",
                             review_reason=None if ok else "mục cần sửa cụm từ không có trong văn bản")
                return
            # Lấy phần sau chữ "tại" CUỐI: cụm từ trong ngoặc có thể chứa "quy định tại điểm…"
            at = header.rsplit(" tại ", 1)
            for r in [x.merged(ctx) for x in parse_refs(at[1])] if len(at) > 1 else (refs or [ctx]):
                emit(node, idx, target_so_hieu=so_hieu, target_key=r.key(dkey) if r.dieu else "",
                     action="unsupported", new_text=None, parse_status="needs_review",
                     review_reason="mẫu câu chưa hỗ trợ (đoạn/phụ lục/tên Điều)", level=r.level)
            return
        if not refs or any(r.dieu is None for r in refs):
            emit(node, idx, target_so_hieu=so_hieu, target_key="", action=verb or "unsupported",
                 new_text=None, parse_status="needs_review", review_reason="không xác định được mục bị tác động")
            return

        if verb == "bai_bo":
            for r in refs:
                key = r.key(dkey)
                ok = key in existing
                emit(node, idx, target_so_hieu=so_hieu, target_key=key, action="bai_bo", new_text=None,
                     level=r.level, parse_status="ok" if ok else "needs_review",
                     review_reason=None if ok else "mục bị bãi bỏ không có trong văn bản gốc")
                # Bãi bỏ cả Điều/Khoản thì mục con cũng hết hiệu lực
                for old in sorted(k for k in existing if ok and k.startswith(key + "/")):
                    if existing[old]["level"] in ("khoan", "diem"):
                        emit(node, idx, target_so_hieu=so_hieu, target_key=old, action="bai_bo",
                             new_text=None, level=existing[old]["level"], origin="implied_by_replace")
            return

        levels = {r.level for r in refs}
        if len(levels) != 1:
            emit(node, idx, target_so_hieu=so_hieu, target_key=refs[0].key(dkey), action=verb,
                 new_text=None, parse_status="needs_review", review_reason="nhiều cấp trong một câu")
            return
        if not node.content:
            emit(node, idx, target_so_hieu=so_hieu, target_key=refs[0].key(dkey), action=verb, new_text=None,
                 level=refs[0].level, parse_status="needs_review", review_reason="không tìm thấy nội dung mới")
            return
        content = _parse_content(node.content, refs[0], so_hieu)
        # "Sửa đổi khoản 18 và bổ sung khoản 18a vào sau khoản 18": mỗi mục một hành động
        mixed = RE_MIXED_ADD.search(_target_text(header)) if verb == "sua_doi" else None
        added = {(a.khoan, a.diem) for a in parse_refs(mixed.group(1))} if mixed else set()
        base_verb = verb
        for r in refs:
            key = r.key(dkey)
            verb = "bo_sung" if (r.khoan, r.diem) in added else base_verb
            new = content.get(key)
            if new is None:
                emit(node, idx, target_so_hieu=so_hieu, target_key=key, action=verb, new_text=None,
                     level=r.level, parse_status="needs_review", review_reason="không tìm thấy nội dung mới")
                continue
            exists = key in existing
            parent_key = key.rsplit("/", 1)[0]
            if verb == "sua_doi" and not exists:
                status, reason = "needs_review", "mục được sửa không có trong văn bản gốc"
            elif verb == "bo_sung" and exists:
                status, reason = "needs_review", "mục bổ sung đã có trong văn bản gốc"
            elif verb == "bo_sung" and r.level != "dieu" and parent_key not in existing:
                status, reason = "needs_review", "mục cha của mục bổ sung không có trong văn bản gốc"
            else:
                status, reason = "ok", None
            emit(node, idx, target_so_hieu=so_hieu, target_key=key, action=verb, new_text=new.text,
                 level=new.level, title=new.title, parse_status=status, review_reason=reason)
            # Mục con trong nội dung mới (vd khoản 3a có điểm a, b; cả Điều 42 mới)
            new_keys = set()
            for child in new.walk():
                if child is new:
                    continue
                new_keys.add(child.key)
                c_exists = child.key in existing
                emit(node, idx, target_so_hieu=so_hieu, target_key=child.key,
                     action="sua_doi" if c_exists else "bo_sung", new_text=child.text,
                     level=child.level, title=child.title, origin="content_child",
                     parse_status=status, review_reason=reason)
            # Thay cả Khoản/Điều: mục con cũ không còn trong nội dung mới thì hết hiệu lực
            if verb == "sua_doi" and r.level in ("dieu", "khoan") and status == "ok":
                for old in sorted(k for k in existing if k.startswith(key + "/")):
                    if old not in new_keys and existing[old]["level"] in ("khoan", "diem"):
                        emit(node, idx, target_so_hieu=so_hieu, target_key=old, action="bai_bo",
                             new_text=None, level=existing[old]["level"], origin="implied_by_replace")

    def _target_of(node: _ProvNode, inherited: str | None) -> str | None:
        header = node.header.split("“")[0]
        m = RE_TARGET_DOC.search(header) or (RE_DOC_REF.search(header) if node.level != "dieu" else None)
        if m:
            return m.group(1)
        if node.level == "dieu" and inherited is None and target_names:
            name = RE_TARGET_LAW_NAME.search(header)
            return target_names.get(name.group(1).lower()) if name else None
        return inherited

    def walk(node: _ProvNode, ctx: Ref, so_hieu: str | None) -> None:
        header = node.header
        so_hieu = _target_of(node, so_hieu)
        verb = _verb(header)
        instr_children = [c for c in node.children if _verb(c.header)]
        if instr_children:
            # Câu ngữ cảnh: "Sửa đổi, bổ sung một số điểm của khoản 5 như sau:"
            refs, _ = _target_refs(header) if verb else ([], Ref())
            new_ctx = refs[0].merged(ctx) if len(refs) == 1 else ctx
            if len(refs) == 1 and refs[0].level == "diem":
                new_ctx = ctx
            for c in node.children:
                walk(c, new_ctx, so_hieu)
            return
        if verb and so_hieu in target_rows_by_so_hieu:
            leaf(node, ctx, so_hieu)

    for root in build_tree(amending_rows):
        for node in [root] if root.level == "dieu" else [n for n in _iter(root) if n.level == "dieu"]:
            walk(node, Ref(), default_target)
    return out


def _iter(n: _ProvNode):
    yield n
    for c in n.children:
        yield from _iter(c)
