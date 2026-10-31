# Kiểm tra mẫu violations (M5)

Tạo ngày 31/10/2026 từ bảng `violations` (bản đang hiệu lực), 50 dòng theo thứ tự `md5(violation_id || 'm5')`, không chọn tay.

Cột "Mức phạt" đối chiếu với câu dẫn của Khoản trong `provision_versions`: 50/50 khớp (tiêu chí M5: ≥ 90%). Đây là đối chiếu với text đã parse, do Claude thực hiện. **Chưa đối chiếu với văn bản giấy và chưa có người kiểm tra pháp lý.**

| Mục | Mức phạt (đồng) | Đối tượng | Phương tiện | Mức phạt so với nguồn | Hành vi |
|---|---|---|---|---|---|
| `D12/K11/Pc@v1#1` | 6.000.000–8.000.000 | ca_nhan | khong_ap_dung | khớp | Hủy hoại, làm hư hỏng, làm mất tác dụng thiết bị điều khiển, giám sát  |
| `D12/K2/Pc@v1#1` | 200.000–250.000 | ca_nhan | khong_ap_dung | khớp | Điều khiển vật thể bay, tàu bay không người lái, phương tiện bay siêu  |
| `D12/K2/Pd@v1#1` | 200.000–250.000 | ca_nhan | xe_may | khớp | Người được chở trên xe mô tô, xe gắn máy, các loại xe tương tự xe mô t |
| `D12/K2/Pg@v1#1` | 200.000–250.000 | ca_nhan | khong_ap_dung | khớp | Phơi thóc, lúa, rơm, rạ, nông, lâm, hải sản trên đường bộ; đặt máy tuố |
| `D12/K5/Pa@v1#1` | 400.000–600.000 | ca_nhan | xe_may | khớp | Bám, kéo, đẩy xe khác, vật khác, dẫn dắt vật nuôi, mang vác vật cồng k |
| `D13/K2/Pb@v1#1` | 400.000–600.000 | ca_nhan | o_to, xe_4_banh_dong_co | khớp | Điều khiển xe không có còi hoặc có nhưng còi không có tác dụng |
| `D14/K2/Pdd@v1#1` | 2.000.000–3.000.000 | ca_nhan | xe_may | khớp | Sử dụng còi không đúng quy chuẩn kỹ thuật cho từng loại xe |
| `D16/K1/Pc@v1#1` | 800.000–1.000.000 | ca_nhan | o_to, xe_may_chuyen_dung | khớp | Điều khiển xe có các bộ phận chuyên dùng lắp đặt không đúng vị trí; kh |
| `D18/K7/Pa@v1#1` | 6.000.000–8.000.000 | ca_nhan | xe_may | khớp | Có giấy phép lái xe nhưng không phù hợp với loại xe đang điều khiển |
| `D18/K7/Pc@v1#1` | 6.000.000–8.000.000 | ca_nhan | xe_may | khớp | Có giấy phép lái xe quốc tế do các nước tham gia Công ước của Liên hợp |
| `D18/K7/Pd@v1#1` | 6.000.000–8.000.000 | ca_nhan | xe_may | khớp | Sử dụng giấy phép lái xe không hợp lệ (giấy phép lái xe có số phôi ghi |
| `D20/K5/Pl@v2#1` | 1.000.000–2.000.000 | ca_nhan | o_to | khớp | Điều khiển xe kinh doanh vận tải hành khách, xe vận tải nội bộ không l |
| `D20/K5/Pm@v2#1` | 1.000.000–2.000.000 | ca_nhan | o_to | khớp | Điều khiển xe vận tải hành khách theo hợp đồng sử dụng hợp đồng điện t |
| `D20/K7@v1#1` | 5.000.000–7.000.000 | ca_nhan | o_to | khớp | hành vi vi phạm điều khiển xe chở hành khách không có hoặc không gắn p |
| `D21/K6/Pc@v1#1` | 5.000.000–7.000.000 | ca_nhan | o_to, may_keo | khớp | Điều khiển xe không có hoặc không gắn phù hiệu theo quy định (đối với  |
| `D21/K8/Pb@v2#1` | 8.000.000–12.000.000 | ca_nhan | o_to, may_keo | khớp | Điều khiển xe kéo theo rơ moóc, sơ mi rơ moóc mà khối lượng toàn bộ (b |
| `D21/K8/Pd@v2#1` | 8.000.000–12.000.000 | ca_nhan | o_to, may_keo | khớp | Chở thiết bị có hình dạng thùng hoặc có hình dạng như công-ten-nơ (khô |
| `D24/K1@v1#1` | 1.000.000–2.000.000 | ca_nhan | o_to | khớp | hành vi vi phạm vận chuyển động vật sống, thực phẩm tươi sống không ma |
| `D26/K2/Pe@v1#1` | 1.000.000–2.000.000 | ca_nhan | khong_ap_dung | khớp | Sử dụng xe vận chuyển hàng hóa nguy hiểm mà không làm sạch hoặc không  |
| `D26/K4/Pb@v1#1` | 3.000.000–4.000.000 | ca_nhan | o_to | khớp | Sử dụng lái xe, nhân viên phục vụ trên xe để tham gia kinh doanh vận t |
| `D26/K4/Pg@v1#1` | 3.000.000–4.000.000 | ca_nhan | khong_ap_dung | khớp | Không thực hiện việc niêm yết thông tin trên xe theo quy định hoặc có  |
| `D26/K6/Pa@v1#1` | 4.000.000–6.000.000 | ca_nhan | khong_ap_dung | khớp | Sử dụng xe vận chuyển động vật sống không có kết cấu phù hợp với loại  |
| `D26/K7/Pk@v1#1` | 5.000.000–6.000.000 | ca_nhan | o_to | khớp | Sử dụng xe ô tô kinh doanh vận tải hành khách từ 08 chỗ trở lên (không |
| `D29/K2@v1#1` | 2.000.000–3.000.000 | ca_nhan | o_to | khớp | hành vi vi phạm điều khiển xe ô tô cứu hộ giao thông đường bộ không có |
| `D32/K12/Pd@v1#1` | 16.000.000–18.000.000 | ca_nhan | o_to, xe_4_banh_dong_co, xe_may_chuyen_dung | khớp | Đưa phương tiện giao thông thông minh không có giấy phép hoạt động hoặ |
| `D32/K7/Pl@v1#1` | 4.000.000–6.000.000 | ca_nhan | o_to, xe_4_banh_dong_co, xe_may_chuyen_dung | khớp | Cố ý can thiệp làm sai lệch chỉ số trên đồng hồ báo quãng đường đã chạ |
| `D32/K8/Ph@v1#2` | 8.000.000–12.000.000 | to_chuc | xe_may | khớp | Đưa phương tiện không gắn biển số (đối với loại xe có quy định phải gắ |
| `D34/K1@v1#1` | 3.000.000–5.000.000 | ca_nhan | o_to | khớp | hành vi không thực hiện đúng quy định trong giấy phép lưu hành, trừ cá |
| `D36/K2/Pb@v1#1` | 400.000–600.000 | ca_nhan | xe_may, xe_tho_so | khớp | Chở hành lý, hàng hóa vượt quá khổ giới hạn cho phép của xe |
| `D37/K4/Pa@v1#1` | 8.000.000–10.000.000 | ca_nhan | co_gioi | khớp | Điều khiển phương tiện không gắn biển số tạm thời hoặc gắn biển số tạm |
| `D39/K1/Pdd@v1#1` | 2.000.000–3.000.000 | — | khong_ap_dung | khớp | Không có giáo án của môn học được phân công giảng dạy theo quy định ho |
| `D39/K2/Pa@v1#1` | 3.000.000–5.000.000 | — | khong_ap_dung | khớp | Sử dụng xe tập lái không có mui che mưa, nắng; không có ghế ngồi gắn c |
| `D39/K4/Pdd@v1#1` | 10.000.000–20.000.000 | — | khong_ap_dung | khớp | Cơ sở đào tạo lái xe không có đủ hệ thống phòng học; phòng học không đ |
| `D39/K5/Pc@v1#1` | 20.000.000–30.000.000 | — | khong_ap_dung | khớp | Cơ sở đào tạo lái xe xét hoàn thành khóa đào tạo hoặc cấp chứng chỉ sơ |
| `D6/K2/Pc@v1#1` | 600.000–800.000 | ca_nhan | o_to, xe_4_banh_dong_co | khớp | Không tuân thủ các quy định về nhường đường tại nơi đường bộ giao nhau |
| `D6/K4/Pk@v1#1` | 2.000.000–3.000.000 | ca_nhan | o_to, xe_4_banh_dong_co | khớp | Quay đầu xe tại nơi có biển báo hiệu có nội dung cấm quay đầu đối với  |
| `D6/K6/Pc@v1#1` | 6.000.000–8.000.000 | ca_nhan | o_to, xe_4_banh_dong_co | khớp | Điều khiển xe trên đường mà trong máu hoặc hơi thở có nồng độ cồn nhưn |
| `D7/K2/Pc@v1#1` | 400.000–600.000 | ca_nhan | xe_may | khớp | Điều khiển xe chạy tốc độ thấp mà không đi bên phải phần đường xe chạy |
| `D7/K7/Pb@v1#1` | 4.000.000–6.000.000 | ca_nhan | xe_may | khớp | Điều khiển xe đi vào đường cao tốc, trừ xe phục vụ việc quản lý, bảo t |
| `D7/K9/Pb@v1#1` | 8.000.000–10.000.000 | ca_nhan | xe_may | khớp | Điều khiển xe thành nhóm từ 02 xe trở lên chạy quá tốc độ quy định |
| `D8/K4/Pa@v1#1` | 1.000.000–2.000.000 | ca_nhan | xe_may_chuyen_dung | khớp | Chạy quá tốc độ quy định từ 10 km/h đến 20 km/h |
| `D8/K4/Pdd@v1#1` | 1.000.000–2.000.000 | ca_nhan | xe_may_chuyen_dung | khớp | Quay đầu xe ở phần đường dành cho người đi bộ qua đường, trên cầu, đầu |
| `D8/K6/Pb@v2#1` | 3.000.000–5.000.000 | ca_nhan | xe_may_chuyen_dung | khớp | Dừng xe, đỗ xe trên đường cao tốc không đúng nơi quy định; không có bá |
| `D8/K7/Pc@v1#1` | 6.000.000–8.000.000 | ca_nhan | xe_may_chuyen_dung | khớp | Không chấp hành hiệu lệnh của đèn tín hiệu giao thông |
| `D8/K9/Pc@v1#1` | 18.000.000–20.000.000 | ca_nhan | xe_may_chuyen_dung | khớp | Điều khiển xe trên đường mà trong cơ thể có chất ma túy hoặc chất kích |
| `D9/K1/Pc@v1#1` | 100.000–200.000 | ca_nhan | xe_dap, xe_tho_so | khớp | Không chấp hành hiệu lệnh hoặc chỉ dẫn của biển báo hiệu, vạch kẻ đườn |
| `D9/K1/Pg@v1#1` | 100.000–200.000 | ca_nhan | xe_dap, xe_tho_so | khớp | Điều khiển xe đạp, xe đạp máy đi dàn hàng ngang từ 03 xe trở lên, xe t |
| `D9/K1/Pk@v1#1` | 100.000–200.000 | ca_nhan | xe_dap, xe_tho_so | khớp | Để xe ở lòng đường, vỉa hè trái phép; đỗ xe ở lòng đường gây cản trở g |
| `D9/K1/Po@v1#1` | 100.000–200.000 | ca_nhan | xe_dap, xe_tho_so | khớp | Xe đạp, xe đạp máy, xe xích lô chở quá số người quy định, trừ trường h |
| `D9/K1/Pp@v1#1` | 100.000–200.000 | ca_nhan | xe_dap, xe_tho_so | khớp | Điều khiển xe trên đường mà trong máu hoặc hơi thở có nồng độ cồn nhưn |
