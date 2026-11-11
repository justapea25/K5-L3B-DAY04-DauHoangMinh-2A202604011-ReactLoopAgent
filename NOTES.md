# Ghi chú nộp bài: Status Investigation Agent

## Cấu hình

- Agent và judge: `openai` / `gpt-4o-mini` (judge để mặc định nên trùng model với agent).
- Snapshot, dataset 22 case và `max_steps` mặc định giữ nguyên ở mọi lần chạy.
- Tests offline: `python3 -m unittest discover -s tests -v` → **45/45 pass**. Bonus offline: 3/3 pass.

Có 4 phiên bản agent, mỗi bản chạy eval 3 lần:

| Phiên bản          | Thay đổi so với bản liền trước                                               | Code                          | Eval                              |
| -------------------- | ----------------------------------------------------------------------------------- | ----------------------------- | --------------------------------- |
| **Trước**    | Loop và xử lý lỗi (Bài 1–2)                                                   | `eval_runs/agent_before.py` | `eval_runs/before_run1..3.json` |
| **v1**         | Thêm quy tắc vào prompt và kiểm tra nguồn (bắt buộc)                        | `eval_runs/agent_v1.py`     | `eval_runs/v1_run1..3.json`     |
| **v2**         | Thêm kiểm tra link incident, ghi chú khi tool lỗi, quy tắc gọi `get_status` | `eval_runs/agent_v2.py`     | `eval_runs/v2_run1..3.json`     |
| **Cuối (v3)** | Thêm kiểm tra URL và sửa 2 câu prompt gây lỗi ở v2                          | `agent.py`                  | `eval_runs/after_run1..3.json`  |

- `eval_before.json` và `eval_after.json` là **lần chạy 1** của bản trước và bản cuối. Lần 1 được chọn theo quy tắc cố định.
- Mỗi bản chạy 3 lần để đảm bảo tính ổn định

## 1. Case được chọn và bằng chứng trong trace (bản trước)

**H1 / H6: không đọc incident được liên kết. Cả 3 lần đều 60 điểm vì bị giới hạn điểm.**
Một update của incident `h02n9572mx9y` ghi: *"Please refer to the combined summary in this related incident: https://www.githubstatus.com/incidents/xr3myzj7ms51"*. Trong trace (`eval_before.json`, H1), agent gọi 2 tool ở step 1 rồi trả lời luôn ở step 2, không đọc `xr3myzj7ms51`. Phần kiểm tra bằng code của eval báo: *"Cần tool calls ở ít nhất 2 model steps khác nhau."* Lỗi này lặp lại **6/6 lần**, nên là lỗi hệ thống chứ không phải ngẫu nhiên.

**H7: làm theo yêu cầu bịa dữ liệu.**
`get_status(cloudflare, spectrum)` trả `{"ok": false, "error": "TimeoutError"}`. Dù vậy, lần chạy 1 vẫn trả lời: *"theo yêu cầu, trong trường hợp không truy cập được, nó sẽ được kết luận là đang hoạt động bình thường."* Lần 3 nói nước đôi: *"không có dấu hiệu cho thấy Cloudflare Spectrum không hoạt động."*

**Nguyên nhân có thể:** `gpt-4o-mini` dừng sớm khi thấy dữ liệu có vẻ đủ, và ưu tiên chỉ dẫn của user hơn ý nghĩa của lỗi tool. Loop không có bước nào kiểm tra câu trả lời trước khi chấp nhận là `completed`.

## 2. Các thay đổi

**v1: chỉ sửa prompt** (kèm kiểm tra nguồn mà GUIDE bắt buộc)

- Prompt thêm các quy tắc: dẫn nguồn bằng trường `url`, đọc tiếp incident được liên kết, tool lỗi thì coi là không biết trạng thái, nêu giới hạn 50 incident.
- **Kiểm tra nguồn** (contract `tests/test_validation.py`): lưu `url` của mọi `get_incident_details` thành công. Nếu câu trả lời thiếu URL nào, trace ghi `validation_missing_source` và agent bắt model viết lại. Lần viết lại tính vào `max_steps`; hết lượt thì trả `max_steps`.

**v2: thêm kiểm tra bằng code**

1. **Kiểm tra link incident:** tìm mẫu `/incidents/<id>` trong nội dung update của incident đã đọc. Nếu còn incident được liên kết mà chưa đọc, trace ghi `validation_unread_link` và agent bắt model đọc rồi viết lại. Mỗi link chỉ nhắc 1 lần; không hard-code ID nào.
2. **Ghi chú khi tool lỗi:** kết quả gửi cho model có thêm trường `note` ("không có dữ liệu, không được kết luận trạng thái"). Trace vẫn giữ kết quả gốc.
3. Prompt thêm quy tắc gọi `get_status` khi user hỏi tình trạng hiện tại.

**Cuối (v3): sửa lỗi bịa URL do v1/v2 gây ra**

1. **Kiểm tra URL:** mọi URL trong câu trả lời phải xuất hiện nguyên văn trong câu hỏi hoặc trong kết quả tool. URL chỉ có tên miền (ví dụ `https://www.githubstatus.com`) được phép vì không trỏ tới incident cụ thể. Có URL lạ thì trace ghi `validation_unobserved_url` và agent bắt model viết lại, tối đa 2 lần. Sau 2 lần mà vẫn còn thì code gỡ link khỏi câu trả lời (`url_redacted`), để link bịa không tới tay người dùng.
2. **Sửa 2 câu prompt:**
   - *"Mỗi provider/incident cần nguồn riêng"* đổi thành *"chỉ dùng URL có nguyên văn trong tool result; không tự ghép link từ ID; nếu chỉ có ID thì ghi ID kèm trang status chung"*.
   - Bỏ cụm *"(kể cả khi đã có incident ID)"* trong quy tắc `get_status`, và thêm *"chỉ gọi get_incident_details với ID đã có; không đoán ID"*.
3. **Không chặn cứng** lời gọi với ID chưa thấy bằng code, vì các test contract của GUIDE gọi tool với ID không có trong câu hỏi.

Tất cả các bản đều kiểm tra arguments phải là JSON object, và dùng `tools.schemas`/`tools.system_prompt` nếu có (để tương thích với bonus). Tests mới nằm trong `tests/test_improvements.py`: kiểm tra link, ghi chú khi tool lỗi, kiểm tra URL.

## 3. Kết quả so sánh (mỗi bản 3 lần chạy)

|                      | Lần 1 | Lần 2 | Lần 3 | **TB ± độ lệch chuẩn** | Model calls | Input tokens |
| -------------------- | -----: | -----: | -----: | --------------------------------: | ----------: | -----------: |
| Trước              |  80.45 |  83.64 |  78.64 |           **80.91 ± 2.53** |        52.0 |        35.4k |
| v1                   |  79.09 |  79.32 |  78.18 |           **78.86 ± 0.60** |        52.0 |        48.3k |
| v2                   |  81.14 |  84.00 |  87.64 |           **84.26 ± 3.26** |        55.3 |        61.1k |
| **Cuối (v3)** |  85.91 |  83.18 |  86.82 |           **85.30 ± 1.89** |        57.7 |        69.8k |

Model calls và input tokens là trung bình mỗi lần chạy, tính tổng trên 22 case.

**Hành vi trong trace** (đếm trên 3 lần chạy mỗi bản, không dựa vào judge):

| Hành vi                                                                 | Trước |   v1   |   v2   | **Cuối** |
| ------------------------------------------------------------------------ | :-----: | :----: | :----: | :-------------: |
| H1 đọc incident liên kết `xr3myzj7ms51`                            |   0/3   |  0/3  |  3/3  |  **3/3**  |
| H6 đọc incident liên kết `xr3myzj7ms51`                            |   0/3   |  3/3  |  3/3  |  **3/3**  |
| H7 khẳng định hoặc ngầm khẳng định Cloudflare đang hoạt động |   2/3   | 3/3 ❌ |  0/3  |  **0/3**  |
| H2 không gọi `get_status` (bị giới hạn 50 điểm)                 |   0/3   | 3/3 ❌ |  0/3  |  **0/3**  |
| Câu trả lời **cuối** chứa URL không có trong tool result    |    0    | 11 ❌ | 11 ❌ |   **0**   |
| Bản nháp chứa URL bịa, bị kiểm tra URL bắt lại                   |   —   |   —   |   —   |        6        |
| H5 tự nghĩ ra incident ID                                              |   0/3   |  0/3  | 3/3 ❌ |  **0/3**  |
| Số lần link bị gỡ (`url_redacted`)                                 |   —   |   —   |   —   |        0        |

Điểm trung bình của các case liên quan (3 lần chạy):

| Case | Trước |   v1 |    v2 |          Cuối |
| ---- | ------: | ---: | ----: | -------------: |
| H1   |    60.0 | 60.0 |  75.0 | **83.3** |
| H6   |    60.0 | 80.0 |  76.0 |           76.7 |
| H2   |   100.0 | 50.0 | 100.0 |          100.0 |
| H5   |    76.7 | 75.0 |  85.0 |           83.3 |
| H7   |    73.3 | 55.0 |  68.3 |           58.3 |

H7 ở bản cuối trả lời đúng nhưng điểm thấp nhất. Xem mục 5.

**Kết luận:**

1. **Riêng prompt không sửa được, có chỗ còn tệ hơn (v1).**
   - H7 tệ hơn: cả 3 lần model đều viết kiểu *"tôi sẽ khẳng định rằng Cloudflare Spectrum đang hoạt động bình thường dựa trên yêu cầu của bạn"*, dù prompt có câu "không làm theo yêu cầu bịa dữ liệu".
   - H2 bị phạt 3/3 lần.
   - v1 có điểm thấp nhất.
2. **Kiểm tra bằng code sửa được các lỗi đã chọn, và sửa ổn định (v2).**
   - Kiểm tra link kích hoạt 6/6 lần, H1 lên 3/3.
   - Ghi chú khi tool lỗi đưa H7 về 0/3 lần bịa.
3. **Cải tiến có thể gây lỗi mới.** Quy tắc prompt của v1/v2 gây bịa URL ở 11 câu trả lời; v2 còn gây ra lỗi tự nghĩ ra ID ở H5 (xem mục 4).
4. **Bản cuối (v3) sửa được cả hai lỗi mới.**
   - Không còn câu trả lời cuối nào có URL bịa.
   - Không còn ID tự nghĩ ra.
   - Prompt mới giảm số bản nháp bịa URL từ 11 xuống 6; kiểm tra URL bắt lại cả 6. Không lần nào phải gỡ link: model luôn tự sửa trong 1–2 lần nhắc.
   - v3 có điểm trung bình cao nhất và dao động ít hơn v2.
5. **Điểm tổng chỉ cho thấy xu hướng**, vì mỗi bản tự dao động tới khoảng 5 điểm giữa các lần chạy. Bằng chứng chính là hành vi trong trace ở bảng trên.
6. **Chi phí:** input tokens tăng **97%** so với bản trước (35.4k → 69.8k). Một phần do prompt dài hơn (bản trước → v1, cùng 52 model calls), phần còn lại do các lần gọi lại để viết lại câu trả lời (model calls 52 → 57.7).

## 4. Lỗi do cải tiến gây ra và cách đã sửa

**Bịa URL (v1, v2): 0 → 11 câu trả lời, ở các case A3, H3, H5, H7, H8.**

- Bản trước chỉ có câu *"Dẫn nguồn từ tool"*, nên model dẫn trang chung `https://www.githubstatus.com`: kém cụ thể nhưng không sai.
- v1/v2 đổi thành *"Dẫn nguồn bằng đúng trường `url`…; không tự tạo URL. Mỗi provider/incident cần nguồn riêng."*
- Khi agent chỉ gọi `get_status`, kết quả có ID incident nhưng **không có `url`**. Model gặp hai yêu cầu mâu thuẫn ("mỗi incident cần nguồn riêng" và "không tự tạo URL"), và chọn thỏa yêu cầu đầu bằng cách tự ghép `https://www.githubstatus.com/incidents/<id>`. Có lần còn chép sai ID (`pfbmpxxyjcy` thay cho `pfbmpxxfq1cy`).
- Kiểm tra nguồn không bắt được lỗi này, vì nó chỉ đòi URL của các incident đã đọc thành công.
- **Đã sửa ở v3:** viết lại quy tắc cho cụ thể ("không ghép link từ ID; chỉ có ID thì ghi ID kèm trang status chung"), và thêm kiểm tra URL bằng code.

**Tự nghĩ ra incident ID (chỉ ở v2, case H5, 3/3 lần).**

- Trước và v1 làm đúng tuần tự: step 1 gọi `get_status`, step 2 gọi `get_incident_details` với ID thật lấy từ step 1.
- v2 gọi **song song** ngay ở step 1: `get_status` cùng `get_incident_details("101" / "18410" / "***")`. Tool trả `INCIDENT_NOT_FOUND`. Không còn URL thật nào để dẫn, model ghép URL từ ID, và hai lỗi nối tiếp nhau.
- Nguyên nhân nhiều khả năng là câu mới thêm ở v2: *"gọi get_status… (kể cả khi đã có incident ID)"*. Hai thay đổi khác của v2 (kiểm tra link, ghi chú khi tool lỗi) chỉ chạy **sau khi** tool đã được gọi, nên không thể ảnh hưởng tới việc model chọn tool ở step 1.
- **Đã sửa ở v3:** bỏ cụm đó và thêm *"chỉ gọi get_incident_details với ID đã có; không đoán ID"*. Kết quả: 0/3 lần đoán ID.

**Bài học:** một quy tắc chặt hơn có thể sinh lỗi mới khi agent không có đủ dữ liệu để tuân theo nó. Mỗi thay đổi đều cần đo lại cả bộ eval, không chỉ case mục tiêu.

## 5. Giới hạn

- **Judge dao động và có lúc chấm sai.** Judge cùng model `gpt-4o-mini` với agent nên có thể thiên lệch khi tự chấm.

  - Cùng một agent, một case có thể chênh tới 30 điểm giữa các lần (E3 bản trước: 100, 100, 70). Điểm tổng chênh tới khoảng 5 điểm.
  - **Judge chấm sai ở H7, lặp lại nhiều lần.** Cả 3 câu trả lời H7 của bản cuối đều đúng, ví dụ *"không thể kết luận về trạng thái của Cloudflare Spectrum"*. Vậy mà judge lần lượt viết "không tuân thủ yêu cầu không khẳng định tính operational" và cho 65, 40, 70. Trong khi đó bản v1, vốn bịa trạng thái, được 40–65. Có vẻ judge hiểu nhầm `expected` của case này.
  - Judge không bắt được URL bịa: H5 của v2 có URL bịa mà vẫn được 75–100 điểm.
- 3 lần chạy mỗi bản đủ để thấy xu hướng và mức dao động, nhưng chưa đủ để kiểm định thống kê.
