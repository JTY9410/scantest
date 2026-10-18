# 블루투스 OBD2 연결 프로필

모바일 앱과 웹이 블루투스 OBD2 진단기(ELM327·STN·slcan)에 연결할 때 쓰는 설정을 관리자가 등록하고, 앱은 로그인 후 받아 갑니다. 한 번 연결한 진단기는 웹·앱이 각자 기억하고 서버 계정에도 남깁니다. 서버는 진단기에 직접 연결하지 않습니다.

| 사용자 행동 | route | service | 저장 | 결과 |
| --- | --- | --- | --- | --- |
| 프로필·연결한 진단기 목록 | `GET /admin/obd/` | `obd/service.list_profiles`, `obd/devices.list_recent` | - | 프로필(연결 방식, 명령 체계, 기기 이름, BMS 헤더, 조회 명령 수, 제공 여부), 사용자가 연결한 진단기 최근 100대 |
| 등록·수정 | `POST /admin/obd/new`, `/admin/obd/<id>/edit` | `save_profile` | 프로필, 감사기록 | 목록으로 이동. 버전이 다르면 409 |
| 앱이 설정 받기 | `GET /api/obdProfiles` | `enabled_profiles` | - | "앱에 제공"이 켜진 프로필만 camelCase로 (`dialect`, `canBitrate` 포함) |
| 웹이 연결한 진단기 남기기·지우기 | `POST /admin/obd/my-devices`, `DELETE /admin/obd/my-devices/<id>` | `obd/devices.remember`, `forget` | `obd_devices`(platform=web) | 201(새로)·200(고침) `{id}`. CSRF는 `X-CSRFToken` 헤더 |
| 앱이 연결한 진단기 받기·남기기·지우기 | `GET`·`POST /api/obdDevices`, `DELETE /api/obdDevices/<id>` | 같음 | `obd_devices`(platform=app) | `docs/flows/api.md` |

## 입력 규칙

- 연결 방식: BLE(저전력, iPhone·Android) 또는 클래식 SPP(Android 전용). BLE는 서비스·쓰기·알림 UUID 세 개가 모두 있어야 하고, 클래식은 UUID를 저장하지 않습니다.
- 명령 체계: ELM327(기본), STN(OBDLink), slcan(원시 CAN). 모르면 ELM327로 두면 연결할 때 다시 확인합니다. CAN 속도(125k·250k·500k·1M, 기본 자동 감지)는 slcan만 저장합니다. slcan은 AT·ST 초기화 명령을 받지 않습니다.
- UUID는 `FFF0` 같은 4자리 또는 128비트 형식이며 소문자로 저장합니다.
- 초기화 명령은 `AT`/`ST`로 시작하는 줄만 받고, 조회 명령은 16진수 바이트(1~7바이트)만 받습니다. 둘 다 공백을 지우고 대문자로 저장하며 최대 50줄입니다.
- 요청·응답 헤더(CAN ID)는 3자리(11비트) 또는 8자리(29비트) 16진수이고, 둘을 함께 입력해야 합니다.
- 프로필은 지우지 않고 "앱에 제공"을 꺼서 중지합니다.
- 조회 명령에는 검증된 항목만 넣습니다. 차종별 DID 확정은 CAN 역분석(`docs/flows/canlab.md`)의 결과를 따릅니다.

## 위스캔 전용 BLE(BWSI)

광고 이름이 `bwsi`로 시작하는 단말기(예: `bwsia846749d8a76`)는 위스캔 전용 BLE입니다. 웹 `obd-link.js`의 이름 접두사와 기본 프로필 «위스캔 BLE(BWSI)»(`namePrefix=bwsi`)로 고릅니다. 관리자 OBD 목록(`/admin/obd/`)을 열 때 프로필이 없으면 한 번 시드합니다(스캔·수집 화면의 프로필 목록에는 자동으로 넣지 않음 — 이름 접두사만으로도 선택 가능). 프로토콜은 ELM327로 가정하고, 연결 시 `ATI`로 write/notify 채널을 찾습니다. UUID 힌트는 흔한 `fff0`/`fff2`/`fff1`이며 실기와 다르면 «모든 기기»로 고르거나 프로필 UUID를 수정합니다. `ATI` 응답이 없으면 안내 후 다른 프로토콜(전용 드라이버)을 검토합니다.

## 프로필 없이 연결

프로필은 선택 사항입니다. 웹(대시보드·수집 페이지)은 진단기 이름·서비스로 찾고 응답하는 채널을 자동으로 고릅니다(`docs/flows/canlab.md`의 "블루투스 진단기 연결"). 프로필은 특정 진단기의 UUID·초기화 명령을 고정할 때 씁니다.

## 진단기 기억

한 번 연결에 성공한 진단기는 저장됩니다. 웹은 브라우저 `localStorage`의 `wecar.obd.devices`, 앱은 GetStorage의 `obdDevices`에 최근 사용 순서로 최대 5대를 남깁니다.

- 남기는 값: 연결 방식, 기기 주소(BLE id·MAC·호스트), 이름, 명령 체계, 칩·펌웨어, BLE 서비스·쓰기·알림 UUID, 마지막 통신 방식(ATDPN 번호), slcan CAN 속도, 시리얼 속도, 서버 id, 마지막 사용 시각.
- 예전 기억(웹 `wecar.obd.lastDevice`·`transport`·`protocols`, 앱 `lastObdDeviceId`·`Name`)은 처음 실행할 때 새 목록으로 옮기고 지웁니다.
- 자동 연결: 앱은 시작부터 45초마다 15초씩 기억한 BLE 진단기를 최근 순으로 찾고, 최근 클래식(Android 페어링)·WiFi 진단기는 시작할 때 한 번 시도합니다. 웹은 Chrome `getDevices`가 켜진 환경에서 페이지를 열면 가장 최근 진단기에 붙습니다. 사용자가 연결을 끊으면 다시 고를 때까지 멈춥니다.
- 다음 연결: 기억한 명령 체계·UUID·`ATSPA<번호>`·CAN 속도로 바로 연결해 감지 시간을 줄입니다.
- 기억 지우기: 웹 패널의 "기억한 진단기"와 앱 연결 화면의 칩에서 지웁니다. 지금 연결된 진단기면 연결을 끊고, 서버 기록도 지웁니다.
- 서버 계정: 연결할 때마다 같은 사용자·사용처(web·app)·연결 방식·이름이면 고쳐 쓰고, 아니면 새로 남깁니다(사용처별 최대 20대). 이 기기에 기억이 없는 진단기는 같은 계정의 서버 기록(웹·앱 모두)으로 명령 체계·UUID를 미리 채웁니다. 서버에 못 남겨도 기기 기억으로 연결합니다.

## 진단기 명령 체계(드라이버)

연결 방식(BLE·블루투스 클래식·USB·WiFi)은 글자만 주고받고, 명령 체계별 드라이버가 스캔 계획의 `{header, command}`를 진단기 명령으로 바꿉니다. 응답은 모두 ELM327의 `ATH1 ATS1` 형식(`7E8 06 41 00 …`)으로 맞춰 해석기(`scanner`, `canlab`)는 그대로 씁니다. 웹 `obd-driver.js`와 앱 `obd_driver.dart`가 같은 규칙입니다.

| 명령 체계 | 대표 진단기 | 주소 지정 요청 | 비고 |
| --- | --- | --- | --- |
| ELM327 | vLinker, Veepeak, KONNWEI 등 | `ATSH`·`ATCP`·`ATCRA` 뒤 명령 | 모든 OBD 통신 방식(CAN·K-Line·J1850) |
| STN | OBDLink MX+·CX·LX | `STPX h:<주소>, d:<데이터>, t:<ms>` 한 번 | `?`로 거절하면 ELM327 방식으로 보냄. 버퍼가 커서 BUFFER FULL 복구 없음 |
| slcan | CANable, WiCAN, ESP32·nRF BLE-CAN | Lawicel `t`·`T` 프레임과 ISO-TP(첫 프레임·흐름 제어·연속 프레임)를 직접 처리 | CAN 차량만. `ATDPN` 외 AT·ST 명령(`ATRV` 전압 포함)은 "쓰지 않는 명령"으로 건너뜀 |

명령 체계는 프로필 → 이 기기 기억·서버 기록 → 연결해서 묻기 순서로 정합니다. 묻기는 `ATI`에 ELM이 답하면 `STDI`로 STN인지 가리고, 답이 없으면 slcan 버전(`V`)을 묻습니다.

slcan은 첫 요청 때 `0100`을 500k 11비트 → 500k 29비트 → 250k 11비트 → 250k 29비트 순서로 보내 차량 버스를 찾고(프로필·기억에 CAN 속도가 있으면 그 속도 먼저), `ATDPN`에 `A6`~`A9`로 답합니다. 응답 대기(`7F xx 78`)는 5초씩 더 기다리고, 사용 중(`7F xx 21`)은 한 번 다시 보냅니다.

## 진단기 명령

스캔 계획(`docs/flows/scanner.md`)을 보내기 전후에 ELM327·STN 드라이버가 진단기에 보내는 명령입니다.

| 때 | 명령 | 이유 |
| --- | --- | --- |
| 연결 직후 | `ATZ`, `ATE0`, `ATL0`, 통신 방식 (프로필 초기화 명령이 있으면 그것) | 초기화, 에코·줄바꿈 끄기 |
| 형식 | `ATH1`, `ATS1`, `ATCAF1`, `ATAT1` | 응답 주소·공백을 붙여 받고 ISO-TP 형식 맞춤, 대기 시간 자동 조절. 프로필 초기화 명령이 같은 항목을 정했으면 덮어쓰지 않음 |
| 칩 확인 | `ATI`, `STDI`(STN), `ATRV` | 진단기 종류, 전압 |
| 통신 방식 | `ATSP0`, 기억한 방식이 있으면 `ATSPA<n>` | 첫 `0100`은 30초까지 기다리고, 찾은 방식을 진단기별로 기억 |
| 제어기 대기 시간 | `ATST19`(제어기 순회 단계, ≈100ms), 다른 단계로 넘어가면 `ATST32` | 응답 없는 제어기를 빨리 넘김. STN은 `STPX t:100`, slcan은 첫 응답 대기 200ms |
| 제어기 주소 | `ATSH`·`ATCP`·`ATCRA` | `docs/flows/scanner.md`의 "스캔 계획" 주소 규칙. 방송(`7DF`) 요청 전에는 `ATCRA`를 풀어 둠 |

- 명령은 한 번에 하나씩 보내고, 스캔·빠른 점검·수집이 같은 진단기를 동시에 쓰지 않게 막습니다. 초기화 명령에 `OK`가 없으면 연결 실패로 봅니다.
- 시간이 지난 뒤 늦게 온 응답(`>`)은 다음 명령 전에 버려 응답이 하나씩 밀리지 않게 합니다.
- 연결이 끊기면 기다리던 명령을 바로 실패시킵니다. 스캔 중 끊기면 남은 단계는 "연결 끊김"으로 기록하고 결과에 오류로 남깁니다(정상 결과로 저장하지 않음).
- 앱은 응답 줄바꿈을 지우지 않고 공백으로 바꿔 ECU별 응답이 붙지 않게 합니다. BLE 쓰기 특성은 `write`·`writeWithoutResponse`, 알림 특성은 `notify`·`indicate` 중 하나만 있어도 쓰고, Android는 MTU 247을 요청한 뒤 MTU에 맞춰 나눠 씁니다.
- UDS 고장코드(`19 02`·`19 15`) 해석은 웹 `obd-plan.js`, 앱 `ObdPlan.udsDtcs` 하나로 합쳤습니다(29비트 주소 포함).

### 오류 복구

진단기 오류는 각각 한 번만 복구해 다시 보냅니다(웹 `obd-plan.js`의 `recovery`, 앱 `ObdPlan.recovery`가 같음).

| 응답 | 복구 |
| --- | --- |
| `STOPPED` | 다시 보냄 |
| `BUFFER FULL`, `RX ERROR`, `DATA ERROR` | `ATS0`(공백 없이 받아 버퍼 절약)으로 다시 보낸 뒤 `ATS1` |
| `CAN ERROR`, `BUS INIT…`, `BUS ERROR` | `ATPC`(프로토콜 닫기) 후 다시 보냄 |
| `7F xx 78`(응답 대기)만 받음 | `ATSTFF`로 대기 시간을 늘려 5초 이상으로 2회(지우기 단계는 `pending_retries` 6회)까지 다시 보낸 뒤 `ATST32` |
| `7F 14 7F`(지우기, 현재 세션에서 지원 안 함) | 지우기 계획의 `session_fallback` 단계에서만 그 제어기에 `1003` → `14FFFFFF` → `1001`(실패해도 `1001`은 보냄) |
| `7F xx 21`(사용 중)만 받음 | 200ms 뒤 다시 보냄 |
| `NO DATA`, 시간 초과 | 복구하지 않음. 그 제어기의 첫 요청(`22F190`)이면 나머지 요청을 건너뜀 |

## 지원 진단기

ELM327·STN·slcan 명령을 받는 진단기는 연결 방식과 관계없이 씁니다. 웹은 BLE·블루투스 클래식·USB, 앱은 BLE·블루투스 클래식(Android)·WiFi를 지원합니다. 방식별 차이는 `docs/flows/scanner.md`의 "연결 방식"을 봅니다. J2534 패스스루, 제조사 전용 프로토콜(예: BlueDriver), DoIP는 지원하지 않습니다.

실차 확인 목록(배포 뒤 사람이 확인):

- ELM327(vLinker MC+ 등) BLE·클래식: 연결, 스캔, 고장코드, 끊었다 다시 연결 시 자동 연결과 `ATSPA<n>`.
- OBDLink(STN) BLE: 명령 체계가 STN으로 표시되는지, `STPX`로 제어기별 요청이 되는지.
- slcan BLE-CAN(WiCAN 등): 11비트 차량(현대·기아 대부분)과 29비트 차량에서 버스 감지, VIN(여러 프레임), 고장코드.
- 웹과 앱에서 같은 계정으로 연결한 뒤 관리자 "연결한 진단기"에 남는지, 기억 지우기 뒤 서버 기록도 지워지는지.

## LTE 단말기

설정 > OBD2 연결 화면 아래에서 LTE 단말기를 등록하고 토큰을 발급합니다. 흐름은 `docs/flows/telematics.md`입니다.
