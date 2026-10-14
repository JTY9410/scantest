"""UDS(ISO 14229) 요청·응답 짝짓기와 서비스별 해석."""

from dataclasses import dataclass, field

from app.modules.canlab.engine.isotp import Message

# OBD2 모드(01·03·07·09·0A, SAE J1979), KWP2000 21(로컬 ID 읽기), UDS(ISO 14229)
REQUEST_SERVICES = {0x01, 0x03, 0x07, 0x09, 0x0A, 0x10, 0x14, 0x19, 0x21, 0x22, 0x27, 0x2E, 0x31, 0x3E}
RESPONSE_PENDING = 0x78
RESPONSE_WINDOW_MS = 3000

# ISO 14229-1 부정 응답 코드(NRC)
NEGATIVE_CODES = {
    0x10: "일반 거부", 0x11: "지원하지 않는 서비스", 0x12: "지원하지 않는 하위기능",
    0x13: "길이·형식 오류", 0x14: "응답이 너무 김", 0x21: "ECU 사용 중(다시 요청)",
    0x22: "조건 불충족(시동·기어·속도 등)", 0x24: "요청 순서 오류", 0x25: "하위 ECU 응답 없음",
    0x26: "실패로 동작 불가", 0x31: "범위 밖 요청(지원하지 않는 DID)", 0x33: "보안 접근 거부",
    0x35: "보안 키 불일치", 0x36: "보안 시도 횟수 초과", 0x37: "보안 대기 시간 미경과",
    0x70: "업로드·다운로드 거부", 0x71: "전송 중단", 0x72: "프로그래밍 실패", 0x73: "블록 순서 오류",
    0x78: "응답 대기 중", 0x7E: "현재 세션에서 지원하지 않는 하위기능",
    0x7F: "현재 세션에서 지원하지 않는 서비스", 0x81: "엔진 회전수 너무 높음", 0x82: "엔진 회전수 너무 낮음",
    0x83: "엔진 작동 중", 0x84: "엔진 정지 상태", 0x85: "엔진 작동 시간 부족", 0x86: "온도 너무 높음",
    0x87: "온도 너무 낮음", 0x88: "차속 너무 높음", 0x89: "차속 너무 낮음", 0x8A: "가속 페달 너무 높음",
    0x8B: "가속 페달 너무 낮음", 0x8C: "변속기 중립 아님", 0x8D: "변속기 기어 아님",
    0x8F: "브레이크 스위치 열림", 0x90: "변속 레버 P 아님", 0x91: "토크 컨버터 클러치 잠김",
    0x92: "전압 너무 높음", 0x93: "전압 너무 낮음",
}

# 응답 DID로 확인되는 ECU만 이름을 붙인다. 나머지는 ID로 표시한다.
KNOWN_ECUS = {0x7E4: "BMS(배터리 관리)", 0x7C6: "계기판(CLU)"}


@dataclass
class Transaction:
    t_ms: float
    request_id: int
    response_id: int | None
    service: int
    request: bytes
    response: bytes | None = None
    negative_code: int | None = None
    extra_responders: list[int] = field(default_factory=list)

    @property
    def did(self) -> int | None:
        if self.service == 0x22 and len(self.request) >= 3:
            return (self.request[1] << 8) | self.request[2]
        return None

    @property
    def positive(self) -> bool:
        return self.response is not None and self.negative_code is None

    @property
    def data(self) -> bytes:
        """긍정 응답에서 서비스 ID와 DID 에코를 뺀 데이터."""
        if not self.positive:
            return b""
        skip = {0x22: 3, 0x21: 2}.get(self.service, 1)
        return self.response[skip:]


def ecu_label(can_id: int) -> str:
    return KNOWN_ECUS.get(can_id, f"ECU {can_id:03X}")


def _is_request(message: Message) -> bool:
    return bool(message.payload) and message.payload[0] in REQUEST_SERVICES


def _answers(message: Message, service: int) -> bool:
    payload = message.payload
    if not payload:
        return False
    if payload[0] == service + 0x40:
        return True
    return len(payload) >= 3 and payload[0] == 0x7F and payload[1] == service


def pair_transactions(messages: list[Message]) -> list[Transaction]:
    """요청 뒤 3초 안의 응답을 짝짓는다. 물리 주소는 요청 ID+8, 7DF는 7E8~7EF 전체를 받는다."""
    transactions: list[Transaction] = []
    used: set[int] = set()
    for index, message in enumerate(messages):
        if not message.complete or not _is_request(message) or index in used:
            continue
        service = message.payload[0]
        broadcast = message.can_id == 0x7DF
        expected = None if broadcast else message.can_id + 8
        tx = Transaction(message.t_ms, message.can_id, expected, service, message.payload)
        for later_index in range(index + 1, len(messages)):
            later = messages[later_index]
            if later.t_ms - message.t_ms > RESPONSE_WINDOW_MS:
                break
            if later_index in used or not later.complete or not _answers(later, service):
                continue
            if broadcast:
                if not 0x7E8 <= later.can_id <= 0x7EF:
                    continue
            elif later.can_id != expected:
                continue
            payload = later.payload
            if payload[0] == 0x7F and payload[2] == RESPONSE_PENDING:
                used.add(later_index)
                continue
            used.add(later_index)
            if tx.response is None:
                tx.response_id = later.can_id
                tx.response = payload
                tx.negative_code = payload[2] if payload[0] == 0x7F else None
                if not broadcast:
                    break
            else:
                tx.extra_responders.append(later.can_id)
        transactions.append(tx)
    return transactions


def did_samples(transactions: list[Transaction]) -> dict[tuple[int, int], list[tuple[float, bytes]]]:
    """(요청 ID, DID)별 긍정 응답 데이터 목록."""
    samples: dict[tuple[int, int], list[tuple[float, bytes]]] = {}
    for tx in transactions:
        if tx.service == 0x22 and tx.positive and tx.did is not None:
            samples.setdefault((tx.request_id, tx.did), []).append((tx.t_ms, tx.data))
    return samples


def format_dtc(b1: int, b2: int, b3: int) -> str:
    """SAE J2012 표기(P0A7F)에 고장유형 바이트를 붙인다. 위카 앱 해석과 같다."""
    prefix = "PCBU"[b1 >> 6]
    return f"{prefix}{(b1 >> 4) & 0x03}{b1 & 0x0F:X}{b2:02X}{b3:02X}"


def parse_dtcs(tx: Transaction) -> list[dict]:
    """19 02(상태 마스크로 DTC 읽기) 응답의 DTC 목록."""
    if tx.service != 0x19 or not tx.positive or len(tx.response) < 3 or tx.response[1] != 0x02:
        return []
    records = tx.response[3:]
    dtcs = []
    for offset in range(0, len(records) - 3, 4):
        b1, b2, b3, status = records[offset : offset + 4]
        dtcs.append({
            "code": format_dtc(b1, b2, b3),
            "status": status,
            "confirmed": bool(status & 0x08),
            "active": bool(status & 0x01),
        })
    return dtcs


def find_vin(transactions: list[Transaction]) -> str | None:
    for tx in transactions:
        if not tx.positive:
            continue
        raw = b""
        if tx.service == 0x22 and tx.did == 0xF190:
            raw = tx.data
        elif tx.service == 0x09 and len(tx.response) > 2 and tx.response[1] == 0x02:
            raw = tx.response[3:]
        text = "".join(chr(b) for b in raw if 0x30 <= b <= 0x5A)
        if len(text) >= 17:
            return text[-17:]
    return None


def mask_vin(vin: str | None) -> str | None:
    """차대번호는 앞 11자리만 보여 준다. 일련번호(뒤 6자리)는 개인 식별에 쓰일 수 있다."""
    return f"{vin[:11]}******" if vin else None
