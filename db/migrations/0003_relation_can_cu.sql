-- 0003: thêm loại quan hệ `can_cu` (văn bản đang xem căn cứ vào dst), xem docs/DECISIONS.md D-009.
ALTER TABLE document_relations DROP CONSTRAINT document_relations_relation_type_check;
ALTER TABLE document_relations ADD CONSTRAINT document_relations_relation_type_check
  CHECK (relation_type IN
    ('sua_doi','bi_sua_doi','thay_the','bi_thay_the','huong_dan','duoc_huong_dan','bai_bo','can_cu'));
