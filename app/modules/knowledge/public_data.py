"""SAE J1979·J2012와 ISO 14229에 공개된 읽기 명령·수식·고장코드.

제조사 전용 코드는 여기 없다. 세션 변경·보안 접근·쓰기·지우기는 이름만 두고 기본 스캔에 넣지 않는다.
"""

COMMANDS = [
    {"command": "0104", "detail_name": "계산된 엔진 부하", "description": "SAE J1979 PID 04. 엔진이 낼 수 있는 힘 가운데 지금 쓰는 비율입니다.", "status": "verified"},
    {"command": "0105", "detail_name": "엔진 냉각수 온도", "description": "SAE J1979 PID 05. 냉각수 온도입니다.", "status": "verified"},
    {"command": "010C", "detail_name": "엔진 회전수", "description": "SAE J1979 PID 0C. 크랭크축이 1분에 몇 번 도는지입니다.", "status": "verified"},
    {"command": "010D", "detail_name": "차속", "description": "SAE J1979 PID 0D. 차량 속도입니다.", "status": "verified"},
    {"command": "0111", "detail_name": "스로틀 개도", "description": "SAE J1979 PID 11. 스로틀 밸브가 열린 비율입니다.", "status": "verified"},
    {"command": "012F", "detail_name": "연료 잔량", "description": "SAE J1979 PID 2F. 연료 탱크 잔량 비율입니다.", "status": "verified"},
    {"command": "0142", "detail_name": "제어 모듈 전압", "description": "SAE J1979 PID 42. 제어기가 보는 공급 전압입니다.", "status": "verified"},
    {"command": "01A6", "detail_name": "적산 주행거리", "description": "SAE J1979 PID A6. 차량 적산 주행거리입니다.", "status": "verified"},
    {"command": "03", "detail_name": "확정 고장코드", "description": "SAE J1979 모드 03. 배출 관련 확정 고장코드를 읽습니다.", "status": "verified"},
    {"command": "07", "detail_name": "대기 고장코드", "description": "SAE J1979 모드 07. 아직 확정되지 않은 고장코드를 읽습니다.", "status": "verified"},
    {"command": "0A", "detail_name": "영구 고장코드", "description": "SAE J1979 모드 0A. 지워지지 않는 영구 고장코드를 읽습니다.", "status": "verified"},
    {"command": "0902", "detail_name": "차대번호", "description": "SAE J1979 모드 09 INFOTYPE 02. 차량 식별 번호를 읽습니다.", "status": "verified"},
    {"command": "1902FF", "detail_name": "고장코드 상태 읽기", "description": "ISO 14229 서비스 19 하위 02. 상태 마스크에 맞는 고장코드를 읽습니다.", "status": "verified"},
    {"command": "22F190", "detail_name": "제어기 차대번호", "description": "ISO 14229 DID F190. 제어기에 저장된 차대번호를 읽습니다.", "status": "verified"},
    {"command": "04", "detail_name": "고장코드 지우기(모드 04)", "description": "배출 고장코드를 지웁니다. 기본 스캔에서는 보내지 않습니다.", "status": "draft"},
    {"command": "1003", "detail_name": "확장 진단 세션", "description": "진단 세션을 바꿉니다. 기본 스캔에서는 보내지 않습니다.", "status": "draft"},
    {"command": "14FFFFFF", "detail_name": "고장코드 지우기", "description": "UDS 서비스 14. 저장된 고장코드를 지웁니다. 기본 스캔에서는 보내지 않습니다.", "status": "draft"},
]

FORMULAS = [
    {"pid": "04", "detail_name": "계산된 엔진 부하", "formula": "A * 100 / 255", "unit": "%"},
    {"pid": "05", "detail_name": "엔진 냉각수 온도", "formula": "A - 40", "unit": "°C"},
    {"pid": "0C", "detail_name": "엔진 회전수", "formula": "((A * 256) + B) / 4", "unit": "rpm"},
    {"pid": "0D", "detail_name": "차속", "formula": "A", "unit": "km/h"},
    {"pid": "11", "detail_name": "스로틀 개도", "formula": "A * 100 / 255", "unit": "%"},
    {"pid": "2F", "detail_name": "연료 잔량", "formula": "A * 100 / 255", "unit": "%"},
    {"pid": "42", "detail_name": "제어 모듈 전압", "formula": "((A * 256) + B) / 1000", "unit": "V"},
    {"pid": "A6", "detail_name": "적산 주행거리", "formula": "((A * 16777216) + (B * 65536) + (C * 256) + D) / 10", "unit": "km"},
]

# SAE J2012 일반 코드. type은 스캔 마스터(codes)의 ev/ice 구분이다.
DTCS = [
    {"code": "P0100", "type": "ice", "unit_name": "공기량 센서", "detail_name": "질량 또는 체적 공기유량 회로 고장", "description": "질량 또는 체적 공기유량 센서 회로에 고장이 감지되었습니다.", "root_cause": "센서 배선, 커넥터, 센서 자체 불량"},
    {"code": "P0101", "type": "ice", "unit_name": "공기량 센서", "detail_name": "질량 또는 체적 공기유량 회로 범위/성능 이상", "description": "질량 또는 체적 공기유량 센서 신호가 허용 범위 또는 성능 기준을 벗어났습니다.", "root_cause": "흡기 누설, 센서 오염"},
    {"code": "P0115", "type": "ice", "unit_name": "냉각수온 센서", "detail_name": "엔진 냉각수 온도 회로 고장", "description": "엔진 냉각수 온도 센서 회로에 고장이 감지되었습니다.", "root_cause": "센서 배선 단선·단락"},
    {"code": "P0116", "type": "ice", "unit_name": "냉각수온 센서", "detail_name": "엔진 냉각수 온도 회로 범위/성능 이상", "description": "엔진 냉각수 온도 센서 신호가 허용 범위 또는 성능 기준을 벗어났습니다.", "root_cause": "서모스탯, 센서 응답 지연"},
    {"code": "P0120", "type": "ice", "unit_name": "스로틀", "detail_name": "스로틀/페달 위치 센서 또는 스위치 A 회로 고장", "description": "스로틀 또는 페달 위치 센서·스위치 A 회로에 고장이 감지되었습니다.", "root_cause": "센서 전원, 접지, 신호선"},
    {"code": "P0130", "type": "ice", "unit_name": "산소센서", "detail_name": "산소 센서 회로 고장, 뱅크 1 센서 1", "description": "뱅크 1 센서 1 산소 센서 회로에 고장이 감지되었습니다.", "root_cause": "센서 히터, 배선, 배기 누설"},
    {"code": "P0171", "type": "ice", "unit_name": "연료 계통", "detail_name": "연료 보정 시스템 희박, 뱅크 1", "description": "뱅크 1의 연료 혼합기가 지나치게 희박한 상태입니다.", "root_cause": "흡기 누설, 연료 압력 부족, MAF"},
    {"code": "P0172", "type": "ice", "unit_name": "연료 계통", "detail_name": "연료 보정 시스템 농후, 뱅크 1", "description": "뱅크 1의 연료 혼합기가 지나치게 농후한 상태입니다.", "root_cause": "인젝터 누설, 연료 압력 과다, 센서"},
    {"code": "P0300", "type": "ice", "unit_name": "엔진", "detail_name": "임의/복수 실린더 실화 감지", "description": "특정 실린더에 한정되지 않은 실화 또는 여러 실린더의 실화가 감지되었습니다.", "root_cause": "점화 계통, 연료, 압축 압력"},
    {"code": "P0301", "type": "ice", "unit_name": "엔진", "detail_name": "1번 실린더 실화 감지", "description": "1번 실린더에서 실화가 감지되었습니다.", "root_cause": "점화코일, 플러그, 인젝터, 압축"},
    {"code": "P0302", "type": "ice", "unit_name": "엔진", "detail_name": "2번 실린더 실화 감지", "description": "2번 실린더에서 실화가 감지되었습니다.", "root_cause": "점화코일, 플러그, 인젝터, 압축"},
    {"code": "P0303", "type": "ice", "unit_name": "엔진", "detail_name": "3번 실린더 실화 감지", "description": "3번 실린더에서 실화가 감지되었습니다.", "root_cause": "점화코일, 플러그, 인젝터, 압축"},
    {"code": "P0304", "type": "ice", "unit_name": "엔진", "detail_name": "4번 실린더 실화 감지", "description": "4번 실린더에서 실화가 감지되었습니다.", "root_cause": "점화코일, 플러그, 인젝터, 압축"},
    {"code": "P0325", "type": "ice", "unit_name": "노크 센서", "detail_name": "노크 센서 1 회로 고장, 뱅크 1 또는 단일 센서", "description": "뱅크 1 또는 단일 센서에 해당하는 노크 센서 1 회로에 고장이 감지되었습니다.", "root_cause": "센서 배선, 센서 고정"},
    {"code": "P0335", "type": "ice", "unit_name": "크랭크각 센서", "detail_name": "크랭크축 위치 센서 A 회로 고장", "description": "크랭크축 위치 센서 A 회로에 고장이 감지되었습니다.", "root_cause": "센서와 톤휠 간격, 배선"},
    {"code": "P0340", "type": "ice", "unit_name": "캠각 센서", "detail_name": "캠축 위치 센서 A 회로 고장, 뱅크 1 또는 단일 센서", "description": "뱅크 1 또는 단일 센서에 해당하는 캠축 위치 센서 A 회로에 고장이 감지되었습니다.", "root_cause": "센서 배선, 센서"},
    {"code": "P0401", "type": "ice", "unit_name": "EGR", "detail_name": "배기가스 재순환 유량 부족 감지", "description": "배기가스 재순환(EGR) 유량이 기준보다 부족한 것으로 감지되었습니다.", "root_cause": "EGR 통로 막힘, 밸브"},
    {"code": "P0420", "type": "ice", "unit_name": "촉매", "detail_name": "촉매 시스템 효율 임계값 미달, 뱅크 1", "description": "뱅크 1의 촉매 시스템 효율이 임계값보다 낮습니다.", "root_cause": "촉매 열화, 배기 누설, 산소센서"},
    {"code": "P0430", "type": "ice", "unit_name": "촉매", "detail_name": "촉매 시스템 효율 임계값 미달, 뱅크 2", "description": "뱅크 2의 촉매 시스템 효율이 임계값보다 낮습니다.", "root_cause": "촉매 열화, 배기 누설, 산소센서"},
    {"code": "P0440", "type": "ice", "unit_name": "증발가스", "detail_name": "증발가스 배출 제어 시스템 고장", "description": "증발가스 배출 제어 시스템에 고장이 감지되었습니다.", "root_cause": "연료 캡, 호스, 퍼지 밸브"},
    {"code": "P0442", "type": "ice", "unit_name": "증발가스", "detail_name": "증발가스 제어 시스템 누설 감지(소량 누설)", "description": "증발가스 제어 시스템에서 소량 누설이 감지됨", "root_cause": "연료 캡 밀폐, 호스"},
    {"code": "P0455", "type": "ice", "unit_name": "증발가스", "detail_name": "증발가스 제어 시스템 누설 감지(대량 누설)", "description": "증발가스 제어 시스템에서 대량 누설 또는 유량 이상이 감지됨", "root_cause": "연료 캡 열림, 호스 빠짐"},
    {"code": "P0500", "type": "ice", "unit_name": "차속 센서", "detail_name": "차량 속도 센서 A", "description": "차량 속도 센서 신호에 이상이 있음", "root_cause": "센서 배선, 센서"},
    {"code": "P0560", "type": "ice", "unit_name": "전원", "detail_name": "시스템 전압", "description": "차량 시스템 전압에 이상이 있음", "root_cause": "배터리, 발전기, 접지"},
    {"code": "P0600", "type": "ice", "unit_name": "통신", "detail_name": "직렬 통신 링크", "description": "제어 모듈의 직렬 통신 링크에 이상이 있음", "root_cause": "CAN 배선, 제어기 전원"},
    {"code": "P0700", "type": "ice", "unit_name": "변속기", "detail_name": "변속기 제어 시스템(MIL 점등 요청)", "description": "변속기 제어 시스템이 고장 표시등 점등을 요청함", "root_cause": "변속기 제어기 상세 코드 확인"},
    {"code": "P0A80", "type": "ev", "unit_name": "고전압 배터리", "detail_name": "하이브리드/전기차 배터리 팩 교체", "description": "하이브리드/전기차 배터리 팩 교체가 필요함", "root_cause": "셀 불균형, 팩 열화. 제조사 세부 코드는 별도"},
    {"code": "P0AA6", "type": "ev", "unit_name": "고전압 배터리", "detail_name": "하이브리드/전기차 배터리 전압 시스템 절연 고장", "description": "고전압 배터리 시스템의 절연 이상이 감지됨", "root_cause": "고전압 배선 손상, 수분. 제조사 세부 판정은 별도"},
    {"code": "U0100", "type": "ice", "unit_name": "통신", "detail_name": "ECM/PCM A와 통신 두절", "description": "엔진 제어 모듈 또는 파워트레인 제어 모듈 A와 통신이 끊김", "root_cause": "제어기 전원, CAN 배선"},
    {"code": "U0101", "type": "ice", "unit_name": "통신", "detail_name": "변속기 제어 모듈과 통신 두절", "description": "변속기 제어 모듈과 통신이 끊김", "root_cause": "제어기 전원, CAN 배선"},
    {"code": "U0121", "type": "ice", "unit_name": "통신", "detail_name": "ABS 제어 모듈과 통신 두절", "description": "잠김 방지 제동 시스템 제어 모듈과 통신이 끊김", "root_cause": "제어기 전원, CAN 배선"},
]
