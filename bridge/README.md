# J2534 로컬 브리지

Windows PC에서 실행되는 J2534 패스스루 브리지 서버입니다.
scantest 서버와 J2534 DLL 사이의 통신을 중계합니다.

## 구조

```
scantest 서버 (Linux/Mac) <-> HTTP <-> J2534 브리지 (Windows) <-> J2534 DLL <-> 차량
```

## 요구사항

- **Windows 10 이상** (J2534 DLL은 Windows 전용)
- **Python 3.11 이상**
- **J2534 패스스루 장비** (드류텍, 타티스, VCI 등) 및 드라이버 설치

## 설치

### 1. Python 설치

[python.org](https://www.python.org/downloads/)에서 Python 3.11 이상을 다운로드하여 설치합니다.
설치 시 "Add Python to PATH" 옵션을 선택하세요.

### 2. 의존성 설치

PowerShell 또는 명령 프롬프트에서 실행:

```bash
cd bridge
pip install -r requirements.txt
```

### 3. J2534 장비 드라이버 설치

사용하는 J2534 장비의 드라이버를 설치합니다.
드라이버는 보통 Windows 레지스트리에 자동으로 등록됩니다.

**지원 장비 예시:**
- 드류텍 MX+
- 타티스 Techstream Cable
- VCI-3000
- Drew Tech Mongoose Pro
- 기타 SAE J2534-1/-2 호환 장비

### 4. 설치 확인

```bash
python -m bridge.main
```

브라우저에서 http://localhost:5000/api/status 로 접속하여 상태를 확인합니다.

```json
{
  "ready": true,
  "platform": "win32",
  "devices_available": 1,
  "active_devices": 0,
  "active_channels": 0
}
```

## 실행

### 기본 실행

```bash
python -m bridge.main
```

기본적으로 http://0.0.0.0:5000 에서 실행됩니다.

### 환경 변수 설정

```bash
# 포트 변경
set BRIDGE_PORT=8000

# 바인드 주소 변경 (로컬 전용)
set BRIDGE_HOST=127.0.0.1

python -m bridge.main
```

### 자동 시작 (선택 사항)

Windows 시작 프로그램에 등록하거나, Windows 서비스로 실행할 수 있습니다.

**시작 프로그램 등록:**
1. `Win + R` → `shell:startup` 입력
2. 바로가기 만들기:
   - 대상: `C:\Python311\python.exe -m bridge.main`
   - 시작 위치: `C:\path\to\wecarscan\bridge`

## 사용법

### scantest 서버에서 연결

scantest 관리자 화면의 "스캔하기"에서 J2534 연결 방식을 선택하고
브리지 URL을 입력합니다 (예: `http://192.168.1.100:5000`).

### API 엔드포인트

브리지는 다음 REST API를 제공합니다:

- `GET /api/status` - 브리지 상태 확인
- `GET /api/devices` - 사용 가능한 J2534 장비 목록
- `POST /api/device/open` - 장비 열기
- `POST /api/device/close` - 장비 닫기
- `POST /api/channel/connect` - 진단 채널 연결
- `POST /api/channel/disconnect` - 진단 채널 종료
- `POST /api/message/send` - 진단 메시지 전송 및 응답 수신

자세한 API 문서는 http://localhost:5000/docs (Swagger UI)에서 확인할 수 있습니다.

## 문제 해결

### "PassThruSupport.04.04 레지스트리 키를 찾을 수 없습니다"

J2534 장비 드라이버가 설치되지 않았거나 레지스트리에 등록되지 않았습니다.

**해결 방법:**
1. 장비 드라이버를 다시 설치합니다.
2. 레지스트리 편집기(`regedit`)에서 확인:
   ```
   HKEY_LOCAL_MACHINE\SOFTWARE\PassThruSupport.04.04
   ```

### "장비가 연결되지 않았습니다"

- J2534 장비가 PC에 연결되어 있는지 확인합니다 (USB/Bluetooth).
- 장비 LED가 정상 상태인지 확인합니다.
- 다른 프로그램(제조사 소프트웨어 등)이 장비를 사용 중인지 확인합니다.

### "DLL 로드 실패"

- 장비 드라이버가 올바르게 설치되었는지 확인합니다.
- 32비트/64비트 Python과 DLL이 일치하는지 확인합니다.
- 관리자 권한으로 실행해 봅니다.

### 방화벽 설정

scantest 서버에서 브리지에 접근할 수 있도록 Windows 방화벽에서
포트 5000(또는 설정한 포트)을 허용해야 합니다.

**Windows Defender 방화벽 설정:**
1. Windows 보안 → 방화벽 및 네트워크 보호
2. 고급 설정 → 인바운드 규칙 → 새 규칙
3. 포트 → TCP → 특정 로컬 포트: 5000
4. 연결 허용 → 이름: "J2534 Bridge"

## 지원 프로토콜

- **ISO 15765-4 (CAN)** - 대부분의 최신 차량
- **ISO 14230-4 (KWP2000)** - 2000년대 차량
- **ISO 9141-2 (K-Line)** - 1990년대 차량
- **SAE J1850 VPW/PWM** - GM, Ford 등 미국 차량

## 보안 주의사항

- 브리지는 **로컬 네트워크에서만** 실행하세요.
- 인터넷에 직접 노출하지 마세요.
- 신뢰할 수 있는 장치에서만 실행하세요.
- 중요한 진단 작업 전에 차량 데이터를 백업하세요.

## 라이선스

이 브리지는 WecarScan 프로젝트의 일부이며,
차량 진단 목적으로만 사용해야 합니다.

J2534는 SAE International의 등록 상표입니다.
