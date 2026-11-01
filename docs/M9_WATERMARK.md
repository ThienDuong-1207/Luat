# M9: thí nghiệm watermark

Sinh bởi `eval/run_watermark_experiment.py`, seed 20260105.

**Dữ liệu:** 6.000 event trong 180 phút mô phỏng, 493 event trễ 2–25 phút (8%), 175 event gửi trùng. Cửa sổ 10 phút, 196 micro-batch, mỗi batch một phút đến.

| Watermark | Câu hỏi đếm được | Độ đầy đủ | Ô (cửa sổ, topic) đúng tuyệt đối | Thumbs down | Dòng bị watermark loại | Độ trễ chốt cửa sổ | State lớn nhất (dòng) |
|---|---|---|---|---|---|---|---|
| 5 phút | 4.522 / 4.830 | 93,62% | 8 / 108 | 127 / 136 | 402 | 6,8 phút | 391 |
| 15 phút | 4.697 / 4.830 | 97,25% | 36 / 108 | 131 / 136 | 173 | 16,8 phút | 1.060 |
| 60 phút (đối chứng) | 4.830 / 4.830 | 100,00% | 108 / 108 | 136 / 136 | 0 | 61,8 phút | 4.089 |

- **Độ trễ chốt cửa sổ:** trung bình từ lúc cửa sổ kết thúc đến lúc watermark vượt qua nó, tính theo thời gian mô phỏng. Output mode update vẫn hiện số tạm ngay; đây là lúc số không đổi nữa.
- **Số trùng** được khử hết trong phạm vi watermark; bản gốc bị loại vì trễ thì bản trùng cũng bị loại.

## Restart từ checkpoint (watermark 10 phút)

Chạy nửa đầu, dừng, chạy tiếp trên cùng checkpoint, rồi xoá commit của batch 196 để ép Spark chạy lại batch đã ghi sink. So với một lần chạy liền mạch:

- Số ô (cửa sổ, topic) khác nhau: **0** trên 108 ô.
- Batch chạy lại có dữ liệu: [196].
- Kết quả: **khớp hoàn toàn**.
