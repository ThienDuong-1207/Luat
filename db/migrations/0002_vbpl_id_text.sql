-- 0002: vbpl_id là chuỗi (số nguyên hoặc UUID), xem docs/DECISIONS.md D-008.
-- Bỏ FK trước khi đổi kiểu khoá được tham chiếu, đổi kiểu, rồi tạo lại FK.

ALTER TABLE document_files DROP CONSTRAINT document_files_vbpl_id_fkey;
ALTER TABLE provisions     DROP CONSTRAINT provisions_vbpl_id_fkey;

ALTER TABLE documents          ALTER COLUMN vbpl_id          TYPE text USING vbpl_id::text;
ALTER TABLE crawl_queue        ALTER COLUMN vbpl_id          TYPE text USING vbpl_id::text;
ALTER TABLE document_files     ALTER COLUMN vbpl_id          TYPE text USING vbpl_id::text;
ALTER TABLE document_relations ALTER COLUMN src_vbpl_id      TYPE text USING src_vbpl_id::text;
ALTER TABLE document_relations ALTER COLUMN dst_vbpl_id      TYPE text USING dst_vbpl_id::text;
ALTER TABLE provisions         ALTER COLUMN vbpl_id          TYPE text USING vbpl_id::text;
ALTER TABLE amendments         ALTER COLUMN amending_vbpl_id TYPE text USING amending_vbpl_id::text;
ALTER TABLE provision_versions ALTER COLUMN source_vbpl_id   TYPE text USING source_vbpl_id::text;
ALTER TABLE chunks             ALTER COLUMN vbpl_id          TYPE text USING vbpl_id::text;

ALTER TABLE document_files ADD CONSTRAINT document_files_vbpl_id_fkey
  FOREIGN KEY (vbpl_id) REFERENCES documents (vbpl_id);
ALTER TABLE provisions ADD CONSTRAINT provisions_vbpl_id_fkey
  FOREIGN KEY (vbpl_id) REFERENCES documents (vbpl_id);

-- Chặn giá trị rác: chỉ số nguyên dương hoặc UUID chữ thường
ALTER TABLE documents ADD CONSTRAINT documents_vbpl_id_format CHECK (
  vbpl_id ~ '^[0-9]+$' OR vbpl_id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
);
