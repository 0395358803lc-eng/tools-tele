
export const SECURITY_TYPE_VI = { login_code: 'Mã đăng nhập', new_login: 'Đăng nhập mới', '2fa_change': 'Thay đổi 2FA', account_deletion: 'Xóa tài khoản', unknown: 'Không rõ' }
export const GROUP_TYPE_VI = { channel: 'Kênh', megagroup: 'Siêu nhóm', group: 'Nhóm', chat: 'Trò chuyện', broadcast: 'Kênh phát' }
export const GONE_REASON_VI = { banned: 'Bị cấm', deactivated: 'Đã vô hiệu hóa', unauthorized: 'Mất xác thực', deleted: 'Đã xóa', removed: 'Đã loại bỏ' }

export const ACCOUNT_STATUS_VI = {
  connected: 'Đã kết nối', disconnected: 'Mất kết nối', connecting: 'Đang kết nối',
  flood_wait: 'Đang chờ FloodWait', banned: 'Bị cấm', error: 'Lỗi',
  unauthorized: 'Chưa xác thực', reconnecting: 'Đang kết nối lại', removed: 'Đã xóa',
}

export const JOB_STATUS_VI = {
  queued: 'Đang xếp hàng', running: 'Đang chạy', cancelling: 'Đang hủy',
  completed: 'Hoàn tất', completed_with_errors: 'Hoàn tất có lỗi', failed: 'Thất bại',
  cancelled: 'Đã hủy', interrupted: 'Bị gián đoạn', pending: 'Đang chờ', skipped: 'Bỏ qua', ok: 'Thành công',
}

export const JOB_TYPE_VI = {
  bulk_action: 'Thao tác hàng loạt', bulk_profile: 'Sửa hồ sơ hàng loạt', bulk_photo: 'Đổi ảnh hàng loạt',
  change_2fa: 'Đổi 2FA hàng loạt', terminate_other_sessions: 'Chấm dứt phiên khác',
  message_send: 'Gửi tin nhắn', message_react: 'Thả cảm xúc', message_view: 'Xem bài viết', wipe_chat: 'Xóa cuộc trò chuyện',
  group_join: 'Tham gia nhóm/kênh', group_leave: 'Rời nhóm/kênh', group_leave_target: 'Rời mục tiêu',
  group_leave_all: 'Rời toàn bộ nhóm/kênh', delete_own_messages: 'Xóa tin nhắn của tôi',
}

export const AUDIT_ACTION_VI = {
  'auth:login': 'Đăng nhập ứng dụng', 'auth:logout': 'Đăng xuất ứng dụng', 'auth:code_sent': 'Gửi mã Telegram',
  'auth:2fa_required': 'Yêu cầu 2FA', 'auth:login_completed': 'Đăng nhập Telegram hoàn tất', 'auth:cancelled': 'Hủy đăng nhập Telegram',
  'auth:qr_started': 'Bắt đầu đăng nhập QR', 'auth:qr_recreated': 'Tạo lại mã QR', 'auth:qr_cancelled': 'Hủy đăng nhập QR',
  'auth:session_folder_sync': 'Đồng bộ thư mục phiên', 'gone:cleared': 'Xóa lịch sử tài khoản mất',
  'group:join': 'Tham gia nhóm/kênh', 'group:leave': 'Rời nhóm/kênh', 'messages:delete_own': 'Xóa tin nhắn của tôi',
  'job:cancel': 'Hủy tác vụ', 'job:retry': 'Chạy lại tác vụ', 'bot:start': 'Gửi /start cho bot',
  'message:chat_send': 'Gửi tin trong trò chuyện', 'message:send': 'Gửi tin nhắn hàng loạt',
  'profile:photo': 'Cập nhật ảnh hồ sơ', 'profile:update': 'Cập nhật hồ sơ', 'profile:username': 'Cập nhật tên người dùng',
  'security:backfill': 'Tải lịch sử bảo mật', 'security:message_read': 'Đánh dấu tin bảo mật đã đọc',
  'security:terminate_others': 'Chấm dứt các phiên khác', 'security:terminate_session': 'Chấm dứt phiên',
  'settings:update': 'Cập nhật cài đặt',
}

export const PEER_KIND_VI = { bot: 'Bot', user: 'Người dùng', channel: 'Kênh', group: 'Nhóm', chat: 'Trò chuyện', unknown: 'Không rõ' }
export const HEALTH_CHECK_VI = {
  database: 'Cơ sở dữ liệu', schema: 'Lược đồ', app_auth: 'Xác thực ứng dụng', telegram: 'Telegram API',
  encrypted_session_store: 'Kho phiên mã hóa', persistent_storage: 'Lưu trữ bền vững', single_instance_guard: 'Chế độ một tiến trình',
}
export const AUDIT_KEY_VI = {
  removed: 'đã_xóa', account_ids: 'id_tài_khoản', phone_suffix: 'đuôi_số_điện_thoại', gone_id: 'id_lịch_sử', reason: 'lý_do',
  source_job_id: 'id_tác_vụ_gốc', type: 'loại', accounts: 'số_tài_khoản', rate_min: 'độ_trễ_tối_thiểu', rate_max: 'độ_trễ_tối_đa',
  concurrency: 'song_song', auto_reconnect: 'tự_kết_nối_lại', notification_sound: 'âm_báo', job_id: 'id_tác_vụ', target: 'mục_tiêu',
}

export const accountStatusVi = (v) => ACCOUNT_STATUS_VI[v] || v || 'Không rõ'
export const jobStatusVi = (v) => JOB_STATUS_VI[v] || v || 'Không rõ'
export const jobTypeVi = (v) => JOB_TYPE_VI[v] || v || 'Không rõ'
export const auditActionVi = (v) => AUDIT_ACTION_VI[v] || v || 'Không rõ'
export const peerKindVi = (v) => PEER_KIND_VI[v] || v || 'Không rõ'
export const healthCheckVi = (v) => HEALTH_CHECK_VI[v] || v || 'Không rõ'
export const auditKeyVi = (v) => AUDIT_KEY_VI[v] || v
export const securityTypeVi = (v) => SECURITY_TYPE_VI[v] || v || 'Không rõ'
export const groupTypeVi = (v) => GROUP_TYPE_VI[v] || v || 'Không rõ'
export const goneReasonVi = (v) => GONE_REASON_VI[v] || v || 'Không rõ'
