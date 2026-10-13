# 관리자 로그인·MFA

| 사용자 행동 | route | service | 저장 | 결과 |
| --- | --- | --- | --- | --- |
| 아이디·비밀번호 입력 | `POST /admin/login` (`auth.login`) | `auth.service.authenticate`, `mark_logged_in` | 로그인 시각, 감사기록 | MFA 꺼짐: 세션 재발급 후 대시보드. 켜짐: `/admin/mfa`로 |
| OTP 6자리 입력 | `POST /admin/mfa` | `verify_otp` | - | 세션 재발급 후 원래 가려던 `/admin` 경로 |
| 비밀번호 변경 | `POST /admin/account` | `change_password` | 비밀번호 해시, 감사기록 | 완료 안내 |
| MFA 등록 | `POST /admin/account/mfa/start` → `/confirm` | `new_otp_secret`, `otp_qr_svg`, `enable_otp` | 암호화된 OTP 비밀값 | QR 표시 → 코드 확인 후 사용 |
| MFA 해제 | `POST /admin/account/mfa/disable` | `disable_otp` | 비밀값 삭제, 감사기록 | 완료 안내 |
| 로그아웃 | `POST /admin/logout` | - | 세션 삭제 | 로그인 화면 |

- 관리자 유형(`type=admin`)만 들어올 수 있습니다. 첫 관리자는 `flask create-admin`으로 만듭니다.
- 로그인·MFA는 IP+아이디 기준 속도 제한(`ADMIN_LOGIN_RATE_LIMIT`)이 있고, 모든 폼은 CSRF 토큰을 검사합니다.
- 첫 로그인 직후 한 번 PWA 설치 안내를 보여 줍니다. "나중에"를 누르면 브라우저에 기억하고, 사이드바 "앱 설치 안내"로 다시 엽니다.
