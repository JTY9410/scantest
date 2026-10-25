```# 다중 전송 방식 차량 진단 시스템

날짜: 2026-10-25  
버전: 1.0  
범위: DoIP, J2534 패스스루 등 모든 연결 방식 지원

## 개요

scantest의 진단 시스템을 확장하여 다양한 연결 방식으로 차량 진단이 가능하도록 구현했습니다.

### 지원하는 연결 방식

| 방식 | 설명 | 환경 | 비고 |
|---|---|---|---|
| **BLE** | 블루투스 저전력 | 브라우저/앱 | 기존 방식 (ELM327 호환) |
| **Serial** | 블루투스 클래식/USB | 브라우저/앱 | 기존 방식 |
| **WiFi** | WiFi OBD 어댑터 | 브라우저/앱 | 기존 방식 |
| **LTE** | LTE 단말기 | 서버 | 기존 방식 |
| **DoIP** | 이더넷 진단 (ISO 13400) | 로컬 서버 | 신규 (OBD 9번 핀) |
| **J2534** | 패스스루 장비 (SAE J2534) | Windows + 로컬 브리지 | 신규 (전용 장비) |

### 주요 특징

- **전송 계층 추상화**: 모든 연결 방식이 동일한 인터페이스를 구현
- **스캔 계획 재사용**: 어떤 방식으로 연결하든 같은 스캔 계획·해석·리포트 사용
- **안전 정책 유지**: 세션 변경(10), 보안(27), 쓰기(2E), 루틴(31), 지우기(04/14) 차단
- **연결 테스트**: 각 방식별 연결 상태 확인 기능

## 구조

### 전송 계층 아키텍처

```
┌─────────────────────────────────────────────────┐
│          스캔 계획 (plan.py)                      │
│     해석 (interpret.py), 리포트 (report.py)       │
└────────────────┬────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────┐
│        전송 계층 추상화 (TransportAdapter)        │
├─────────────────────────────────────────────────┤
│  CanAdapter  │  DoIPAdapter  │  J2534Adapter    │
└──────┬───────┴────────┬──────┴────────┬─────────┘
       │                │               │
       ▼                ▼               ▼
  BLE/Serial/     이더넷/TCP       HTTP/WebSocket
  WiFi/LTE        (차량 직접)    (로컬 브리지 경유)
```

### DoIP 구조

```
scantest 서버 ─TCP 13400─► 차량 DoIP 게이트웨이 ─► ECU들
  (로컬 망)                    (OBD 9번 핀)
```

### J2534 구조

```
scantest 서버 ─HTTP─► 로컬 브리지 (Windows) ─DLL─► J2534 장비 ─► 차량
  (Linux/Mac)          FastAPI 서버           ctypes     (OBD2)
```

## DoIP 진단

### 개요

DoIP(Diagnostics over IP, ISO 13400)는 이더넷을 통한 차량 진단 프로토콜입니다.

### 하드웨어 요구사항

- **OBD2 커넥터 9번 핀**: DoIP 신호선 (차량이 지원하는 경우만)
- **이더넷 케이블** 또는 **WiFi 연결**
- **차량과 같은 네트워크**: 로컬 서버 필요

### 차량 지원 여부 확인

1. OBD2 커넥터 9번 핀에 신호가 있는지 확인
2. 차량 매뉴얼에서 "DoIP", "Ethernet Diagnostics", "Network Diagnostics" 검색
3. 주로 **2015년 이후 유럽/한국 차량**이 지원

### 사용 방법

#### 1. 네트워크 연결

**방법 A: 직접 연결**
- 차량 OBD2 이더넷 → 이더넷 케이블 → PC
- PC 네트워크 설정: 고정 IP (예: 192.168.0.100)
- 차량 게이트웨이 주소 확인 (보통 192.168.0.1 ~ 192.168.0.50)

**방법 B: WiFi**
- 차량이 WiFi AP 모드 지원 시 연결
- SSID와 비밀번호는 차량 매뉴얼 참고

#### 2. 게이트웨이 주소 찾기

```bash
# Linux/Mac
arp-scan --localnet

# Windows
arp -a
```

#### 3. 스캔 실행

관리자 화면 → 스캔하기 → 연결 방식: **DoIP** 선택
- 게이트웨이 주소 입력 (예: 192.168.0.20)
- 포트: 13400 (기본값)
- "연결 테스트" 클릭하여 확인
- "스캔하기" 실행

### 기능

- ✅ 차량 식별 (VIN, EID, GID)
- ✅ 논리주소 기반 ECU 탐색
- ✅ 기능 주소 (E400) 브로드캐스트
- ✅ 표준 OBD2/UDS 읽기 명령
- ❌ 세션 변경, 보안 접근, 쓰기, 루틴, DTC 지우기 (안전 정책)

### 문제 해결

**"게이트웨이에 연결하지 못했습니다"**
- 네트워크 연결 확인 (핑 테스트: `ping 192.168.0.20`)
- 방화벽 설정 확인 (포트 13400 허용)
- 차량 시동을 ON으로

**"DoIP 라우팅 활성화 실패"**
- 차량이 DoIP를 지원하지 않을 수 있음
- OBD2 9번 핀 연결 확인
- 다른 진단 프로그램이 연결 중인지 확인

**"응답 없음"**
- 차량 시동이 ON인지 확인
- 게이트웨이가 절전 모드일 수 있음 (재연결)
- ECU가 해당 명령을 지원하지 않을 수 있음

## J2534 패스스루

### 개요

SAE J2534는 표준 패스스루 진단 인터페이스입니다.
전문 진단 장비로, CAN, K-Line, J1850 등 다양한 프로토콜을 지원합니다.

### 하드웨어 요구사항

- **J2534 호환 장비**:
  - Drew Tech Mongoose Pro
  - Tactrix OpenPort 2.0
  - VCI-3000
  - 기타 SAE J2534-1/-2 인증 장비
- **Windows PC** (DLL이 Windows 전용)
- **장비 드라이버 설치**

### 시스템 구성

```
┌──────────────┐         ┌──────────────┐         ┌──────┐
│ scantest     │ HTTP    │  로컬 브리지   │  DLL    │ 차량  │
│ 서버         ├────────►│  (Windows)   ├────────►│      │
│ (Linux/Mac)  │         │  FastAPI     │  J2534  │      │
└──────────────┘         └──────────────┘  장비   └──────┘
```

### 설치 (Windows PC)

#### 1. J2534 장비 드라이버 설치

장비 제조사 웹사이트에서 드라이버를 다운로드하여 설치합니다.

**확인 방법:**
- 레지스트리 편집기 (`regedit`) 실행
- `HKEY_LOCAL_MACHINE\SOFTWARE\PassThruSupport.04.04` 확인
- 설치된 장비가 하위 키로 표시되어야 함

#### 2. Python 설치

[python.org](https://www.python.org/downloads/)에서 Python 3.11 이상 설치
("Add Python to PATH" 체크)

#### 3. 브리지 설치

```bash
cd bridge
pip install -r requirements.txt
```

#### 4. 브리지 실행

```bash
python -m bridge.main
```

기본적으로 http://localhost:5000 에서 실행됩니다.

**상태 확인:**
http://localhost:5000/api/status

#### 5. 방화벽 설정

Windows Defender 방화벽에서 포트 5000을 허용합니다:
1. Windows 보안 → 방화벽 및 네트워크 보호
2. 고급 설정 → 인바운드 규칙 → 새 규칙
3. 포트 → TCP → 5000
4. 연결 허용

### 사용 방법

#### 1. 브리지 시작 (Windows PC)

```bash
cd bridge
python -m bridge.main
```

터미널에 "J2534 브리지 서버 시작: http://0.0.0.0:5000" 출력 확인

#### 2. 장비 연결

J2534 장비를 PC에 연결 (USB/Bluetooth)하고 차량 OBD2 포트에 연결

#### 3. scantest에서 스캔

관리자 화면 → 스캔하기 → 연결 방식: **J2534** 선택
- 브리지 URL 입력: `http://192.168.x.x:5000` (Windows PC IP)
- 프로토콜 선택: CAN / KWP / K-Line
- 전송 속도: 500000 (CAN) / 10400 (K-Line)
- "연결 테스트" 클릭
- "스캔하기" 실행

### 지원 프로토콜

| 프로토콜 | 설명 | 차량 |
|---|---|---|
| **ISO 15765-4 (CAN)** | CAN 11/29비트 | 2008년 이후 대부분 |
| **ISO 14230-4 (KWP)** | K-Line 고속 | 2000~2010년대 |
| **ISO 9141-2 (K-Line)** | K-Line 표준 | 1996~2008년 |
| **SAE J1850 VPW/PWM** | GM, Ford 등 | 1996~2008년 미국차 |

### 문제 해결

**"J2534 브리지에 연결하지 못했습니다"**
- 브리지가 실행 중인지 확인
- Windows PC IP 주소 확인 (`ipconfig`)
- 방화벽 설정 확인
- scantest 서버와 Windows PC가 같은 네트워크에 있는지 확인

**"장비가 연결되지 않았습니다"**
- J2534 장비가 PC에 연결되었는지 확인 (USB/Bluetooth)
- 장비 LED 상태 확인
- 드라이버가 설치되었는지 확인 (레지스트리 확인)
- 다른 프로그램(제조사 소프트웨어)이 장비를 사용 중인지 확인

**"DLL 로드 실패"**
- 드라이버를 재설치
- 관리자 권한으로 브리지 실행
- Python이 32비트/64비트 DLL과 일치하는지 확인

**"응답 없음"**
- 차량 시동이 ON인지 확인
- 올바른 프로토콜을 선택했는지 확인 (차량 연식에 맞게)
- 전송 속도 확인 (CAN: 500k 또는 250k)

## 테스트

### 단위 테스트

```bash
pytest tests/scanner/test_transport.py -v
```

### 모의 서버로 통합 테스트

#### DoIP 모의 게이트웨이

```bash
# 터미널 1: 모의 게이트웨이
python -m bridge.mock_doip_gateway

# 터미널 2: 테스트
pytest tests/scanner/test_transport.py::test_doip_adapter_with_real_mock_gateway -v
```

#### J2534 모의 브리지

```bash
# 터미널 1: 모의 브리지
python -m bridge.mock_server

# 터미널 2: 테스트
pytest tests/scanner/test_transport.py::test_j2534_adapter_with_real_mock_bridge -v
```

### 실제 장비 테스트

**실장비 테스트 체크리스트** (PR 전 수동 확인):

- [ ] DoIP: 실제 지원 차량으로 연결 테스트
- [ ] DoIP: 차량 식별 (VIN) 읽기
- [ ] DoIP: 여러 ECU 응답 수집
- [ ] J2534: Windows에서 실제 장비로 연결 테스트
- [ ] J2534: 브리지 → 장비 → 차량 전체 흐름
- [ ] 안전 정책: 차단된 명령(10, 27, 2E, 31, 04, 14)이 거부되는지 확인

## 안전 정책

### 차단된 명령

다음 명령은 **모든 전송 방식**에서 차단됩니다:

- `10` (진단 세션 변경)
- `27` (보안 접근)
- `2E` (데이터 쓰기)
- `31` (루틴 제어)
- `04` (DTC 지우기, OBD)
- `14 FF FF FF` (DTC 지우기, UDS)

### DTC 지우기 흐름

고장코드 지우기는 `scanner/clear.py`의 별도 흐름으로만 가능:
1. 권한 확인 (`can_clear_dtc`, 관리자 MFA 필수)
2. 사용자 확인 (차량번호 입력)
3. 지우기 전 스캔 저장
4. 1회용 토큰 생성
5. 감사 기록 (`dtc_clear_logs`)
6. `10 03`은 NRC 7F를 받은 제어기에만 사용

### SSRF 방지

- Vercel 환경: DoIP/J2534 직접 연결 차단
- 메타데이터 주소 (`169.254.169.254`) 차단
- 사설망 주소만 허용 (192.168.x.x, 10.x.x.x, 172.16-31.x.x)

## 제한사항

### 실장비 미검증 항목

다음 항목은 실제 장비로 검증하지 못했습니다:

- **DoIP**:
  - [x] TCP 연결 및 라우팅 활성화 (mock 검증)
  - [x] 진단 메시지 송수신 (mock 검증)
  - [x] 기능 주소 브로드캐스트 (mock 검증)
  - [x] ISO-TP 프레임 변환 (mock 검증)
  - [ ] UDP 차량 탐색 (`discover_vehicle`)
  - [ ] 29비트 CAN 주소
  - [ ] 실제 차량으로 전체 스캔
  
- **J2534**:
  - [x] HTTP API 인터페이스 (mock 검증)
  - [x] CAN 프로토콜 인터페이스 (mock 검증)
  - [ ] Windows에서 실제 J2534 DLL 로드
  - [ ] K-Line 프로토콜 (ISO 9141, ISO 14230)
  - [ ] J1850 VPW/PWM 프로토콜
  - [ ] 실제 장비와 차량 연결
  - [ ] 여러 장비 동시 사용

**구현 방식**:
- DoIP: CAN 프로토콜은 완전 구현 및 mock 검증 완료
- J2534: CAN 인터페이스만 구현, K-Line/J1850은 인터페이스만 존재

### 알려진 제한사항

- **DoIP**: 로컬 네트워크에서만 사용 가능 (Vercel 배포 서버 불가)
- **J2534**: Windows 전용 (DLL 제약)
- **프로토콜 자동 감지**: 현재 수동 선택만 지원
- **동시 연결**: 한 번에 하나의 전송 방식만 사용 가능

## 향후 개선 사항

1. **프로토콜 자동 감지**: 차량 정보 기반 최적 방식 제안
2. **멀티 게이트웨이**: 여러 DoIP 게이트웨이 동시 사용
3. **Linux J2534 지원**: Wine 또는 가상화로 Linux에서도 사용
4. **WebSocket 실시간 스트리밍**: 스캔 진행 상황 실시간 표시
5. **캐싱**: 이전 연결 설정 저장 및 재사용

## 참고 자료

### 표준 문서

- **ISO 13400** - DoIP (Diagnostics over IP)
- **SAE J2534-1** - PassThru Device Standard
- **SAE J2534-2** - PassThru Device Extended Addressing
- **ISO 14229** - UDS (Unified Diagnostic Services)
- **ISO 15765-4** - CAN Transport Layer

### 관련 파일

- `app/modules/scanner/transport/` - 전송 계층 구현
- `bridge/` - J2534 로컬 브리지
- `tests/scanner/test_transport.py` - 전송 계층 테스트
- `docs/superpowers/specs/2026-10-25-multi-transport.md` - 이 문서

## 문의

기술 지원 및 문의:
- 위카모빌리티 개발팀
- Email: dev@wecarmobility.com
```
