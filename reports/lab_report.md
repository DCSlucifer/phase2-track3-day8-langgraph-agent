# Day 08 Lab Report — LangGraph Agentic Orchestration

## 1. Team / student

- **Name**: Võ Thành Danh
- **Student ID**: 2A202600503
- **Date**: 2026-05-11 12:38:01
- **Repo/commit**: phase2-track3-day8-langgraph-agent

---

## 2. Architecture

Kiến trúc agent sử dụng **LangGraph StateGraph** bao gồm 11 node và các cạnh định tuyến có điều kiện (conditional routing edges):

```text
START → intake → classify → [conditional routing]
  simple       → answer → finalize → END
  tool         → tool → evaluate → answer → finalize → END
  missing_info → clarify → finalize → END
  risky        → risky_action → approval → tool → evaluate → answer → finalize → END
  error        → retry → tool → evaluate → [retry loop hoặc answer]
  max retry    → dead_letter → finalize → END
```

**Các quyết định thiết kế cốt lõi:**
1. **Phân loại bằng từ khóa theo thứ tự ưu tiên (Priority-ordered keyword classification)**: risky > tool > missing_info > error > simple. Đảm bảo các rủi ro cao luôn bị bắt trước.
2. **Vòng lặp thử lại có giới hạn (Bounded retry loops)**: `evaluate_node` kiểm tra kết quả từ tool, hàm router `route_after_retry` đếm và giới hạn theo `max_attempts`.
3. **Sự can thiệp của con người (HITL)**: Node `approval_node` hỗ trợ song song 2 mode: duyệt giả lập (dùng cho CI/CD test tự động) và dùng `interrupt()` thật (dành cho Web Dashboard).
4. **Lịch sử kiểm toán (Append-only audit trail)**: Các trường `messages`, `tool_results`, `errors`, `events` sử dụng reducer `Annotated[list, add]`.
5. **Đảm bảo điểm kết thúc**: Mọi luồng đều đi đến `finalize` rồi mới tới `END`.

---

## 3. State schema

Danh sách các trường quan trọng và cách cập nhật (ghi đè hay ghi thêm).

| Field | Reducer | Why (Mục đích) |
|---|---|---|
| `thread_id` | overwrite | Mã định danh luồng, bắt buộc để LangGraph checkpointing hoạt động |
| `scenario_id` | overwrite | Liên kết state với kịch bản test để đánh giá metrics |
| `route` | overwrite | Lưu trữ đường đi hiện tại (simple/tool/risky/error/missing_info) |
| `attempt` | overwrite | Đếm số lần thử lại hiện tại trong vòng lặp |
| `max_attempts`| overwrite | Giới hạn số lần thử lại (mặc định là 3) |
| `approval` | overwrite | Lưu quyết định phê duyệt (ApproveDecision) từ node duyệt |
| `messages` | **append** | Lưu lại log hội thoại và quá trình dạng text để dễ đọc |
| `tool_results`| **append** | Lưu lịch sử kết quả thực thi công cụ qua mỗi lần retry |
| `errors` | **append** | Lưu log lỗi sinh ra trong quá trình retry |
| `events` | **append** | Lưu log dạng cấu trúc (structured events) dùng để xuất biểu đồ/metrics |

---

## 4. Scenario results

**Tóm tắt kết quả (Key metrics từ `outputs/metrics.json`)**:
- **Tổng số kịch bản**: 15
- **Tỷ lệ thành công**: 100%
- **Số node trung bình đi qua**: 6.7
- **Tổng số lần retry**: 7
- **Tổng số lần interrupt (HITL)**: 5
- **Xác thực Crash-resume**: ✅ Yes

| Scenario | Expected route | Actual route | Success | Retries | Interrupts | Latency |
|---|---|---|---|---:|---:|---|
| G01_simple | simple | simple | ✅ | 0 | 0 | 36ms |
| G02_simple2 | simple | simple | ✅ | 0 | 0 | 16ms |
| G03_tool | tool | tool | ✅ | 0 | 0 | 23ms |
| G04_tool2 | tool | tool | ✅ | 0 | 0 | 24ms |
| G05_tool3 | tool | tool | ✅ | 0 | 0 | 23ms |
| G06_missing | missing_info | missing_info | ✅ | 0 | 0 | 16ms |
| G07_missing2 | missing_info | missing_info | ✅ | 0 | 0 | 17ms |
| G08_risky | risky | risky | ✅ | 0 | 1 | 29ms |
| G09_risky2 | risky | risky | ✅ | 0 | 1 | 29ms |
| G10_risky3 | risky | risky | ✅ | 0 | 1 | 29ms |
| G11_risky4 | risky | risky | ✅ | 0 | 1 | 30ms |
| G12_error | error | error | ✅ | 3 | 0 | 40ms |
| G13_error2 | error | error | ✅ | 3 | 0 | 45ms |
| G14_dead | error | error | ✅ | 1 | 0 | 20ms |
| G15_mixed | risky | risky | ✅ | 0 | 1 | 29ms |

---

## 5. Failure analysis

Phân tích ít nhất hai tình huống lỗi (Failure modes) đã được thiết kế và tính toán:

1. **Retry or tool failure (Công cụ gặp lỗi thoáng qua):**
   - **Tình huống**: Gọi tool bị lỗi mạng hoặc timeout.
   - **Cách giải quyết**: Đã implement `retry_or_fallback_node` và `evaluate_node`. Khi tool trả về lỗi (có chứa chữ "ERROR"), graph rẽ nhánh về node `retry`, tăng biến `attempt`. Vòng lặp sẽ tiếp diễn cho đến khi tool trả về kết quả đúng hoặc `attempt >= max_attempts`. Nếu vượt quá giới hạn, graph sẽ tự động đẩy luồng sang `dead_letter_node` thay vì rơi vào lặp vô tận.
   - **Bằng chứng**: - **G12_error**: Đã thực hiện 3 lần retry, kết quả cuối: thành công=True
- **G13_error2**: Đã thực hiện 3 lần retry, kết quả cuối: thành công=True
- **G14_dead**: Đã thực hiện 1 lần retry, kết quả cuối: thành công=True


2. **Risky action without approval (Hành động rủi ro cao chưa được duyệt):**
   - **Tình huống**: User yêu cầu "refund", "delete", "cancel", "revoke".
   - **Cách giải quyết**: Router sẽ ép buộc điều hướng sang đường `risky`. Luồng bắt buộc phải đi qua `risky_action_node` để chuẩn bị hồ sơ bằng chứng, rồi đi vào `approval_node`. Tại đây, graph sẽ tạm ngưng bằng lệnh `interrupt()` để đẩy popup lên Web UI chờ con người click "Approve" hoặc "Reject" rồi mới được đi tiếp đến `tool_node`.
   - **Bằng chứng**: - **G08_risky**: Cần phê duyệt (approval_required=True), đã phát hiện ngắt để duyệt (interrupts=1)
- **G09_risky2**: Cần phê duyệt (approval_required=True), đã phát hiện ngắt để duyệt (interrupts=1)
- **G10_risky3**: Cần phê duyệt (approval_required=True), đã phát hiện ngắt để duyệt (interrupts=1)
- **G11_risky4**: Cần phê duyệt (approval_required=True), đã phát hiện ngắt để duyệt (interrupts=1)
- **G15_mixed**: Cần phê duyệt (approval_required=True), đã phát hiện ngắt để duyệt (interrupts=1)


---

## 6. Persistence / recovery evidence

Giải thích cách sử dụng checkpointer, thread id, state history và crash-resume:

- **Checkpointer**: Đã thiết lập thành công `SqliteSaver.from_conn_string("crash_demo.db")`.
- **Thread ID**: Mỗi kịch bản (scenario) được cấp một `thread_id` duy nhất (`thread-S01`, `thread-S02`). Việc này đảm bảo state của các câu hỏi khác nhau không bị ghi đè lên nhau trong Database.
- **State history**: Cấu trúc append-only cho phép gọi API `graph.get_state_history()` để lấy toàn bộ danh sách snapshot trong quá khứ, qua đó xây dựng tính năng "Time Travel" trên Web Dashboard (cho phép xem lại state ở từng step cụ thể).
- **Crash-resume evidence**: Đã build tính năng mô phỏng sập máy chủ trên Dashboard. Kết quả: Đã xác minh -- Checkpoint SQLite tồn tại sau khi restart process, không mất state.

---

## 7. Extension work

Mô tả các phần việc mở rộng (bonus) đã hoàn thành:

- **Professional Web Dashboard**: Xây dựng UI tuyệt đẹp bằng FastAPI + CSS/JS thuần (Giao diện Dark Mode), tích hợp biểu đồ Chart.js thống kê thời gian thực.
- **Time Travel UI**: Bảng "State Inspector" bên tay phải của dashboard cho phép click ngược dòng thời gian để xem JSON state ở bất kỳ node nào trong quá khứ.
- **Interactive HITL**: Khi gặp từ khóa nhạy cảm (refund, delete), giao diện web lập tức hiển thị Modal chặn thao tác và yêu cầu Human Approval.
- **Crash-Resume Demo**: Nút bấm giả lập tắt ngỏm server. Chạy bằng SQLite WAL mode đảm bảo dữ liệu phục hồi không sai 1 byte.
- **Mermaid Graph Diagram**: Graph được export tự động qua API ra giao diện dạng Top-Down chuẩn mực.
- **Extended Scenarios**: Bổ sung từ 7 kịch bản lên **15 kịch bản** đa dạng edge cases.
- **Auto-Generated Report**: Tích hợp module auto-render. Khi chạy `python -m langgraph_agent_lab.cli run-scenarios`, hệ thống tự điền Data thật vào file `lab_report.md` này mà không cần gõ tay.

---

## 8. Improvement plan

Nếu có thêm một ngày để đưa hệ thống lên production, tôi sẽ ưu tiên làm các việc sau:

1. **Thay thế Classifier bằng LLM / Router Model**: Hiện tại định tuyến (classify) bằng bộ từ khóa (heuristics). Trên production, tôi sẽ đổi thành 1 node gọi LLM (VD: `gpt-4o-mini`) output ra Structured Data (Pydantic) để phân loại chính xác các câu hỏi tối nghĩa.
2. **Tích hợp API Thực (Real Tool Integration)**: Nối `tool_node` với API thật của CRM/ERP (Salesforce, Stripe) thay vì trả về mock string.
3. **Cơ chế Exponential Backoff**: Áp dụng độ trễ tăng dần (ví dụ: 2s, 4s, 8s) khi gọi tool thất bại để tránh làm sập API bên thứ 3 (Thundering herd problem).
4. **OpenTelemetry / Tracing**: Bổ sung LangSmith hoặc Datadog để trace từng span nhỏ nhất của mỗi node trên hệ thống phân tán.
