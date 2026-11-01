"""트레이스·응답에서 보안 잠금 상태와 NRC를 요약한다(송신 없음)."""

from __future__ import annotations

from app.modules.canlab.engine.features import flag
from app.modules.canlab.engine.uds import NEGATIVE_CODES, Transaction

SECURITY_NRCS = {
    0x33: NEGATIVE_CODES.get(0x33, "보안 접근 거부"),
    0x35: NEGATIVE_CODES.get(0x35, "보안 키 불일치"),
    0x36: NEGATIVE_CODES.get(0x36, "보안 시도 횟수 초과"),
    0x37: NEGATIVE_CODES.get(0x37, "보안 대기 시간 미경과"),
    0x24: NEGATIVE_CODES.get(0x24, "요청 순서 오류"),
    0x78: NEGATIVE_CODES.get(0x78, "응답 대기 중"),
}


def describe_nrc(code: int | None) -> str | None:
    if code is None:
        return None
    return SECURITY_NRCS.get(code) or NEGATIVE_CODES.get(code) or f"NRC 0x{code:02X}"


def unlock_allowed() -> bool:
    """실송신은 STATUS와 UNLOCK이 모두 켜져 있어야 한다. 기본은 둘 다 끔."""
    return flag("SCAN_SECURITY_STATUS") and flag("SCAN_SECURITY_UNLOCK")


def analyze_security_trace(transactions: list[Transaction]) -> dict:
    """0x27·관련 NRC·세션(0x10)·TesterPresent(0x3E) 요약. 페이로드 원문은 넣지 않는다."""
    if not flag("SCAN_SECURITY_STATUS"):
        return {"enabled": False, "events": [], "locked_ecus": [], "sessions": [], "tester_present": 0}

    events = []
    locked = set()
    unlocked = set()
    sessions = []
    tester_present = 0
    for tx in transactions:
        ecu = f"{tx.request_id:03X}"
        if tx.service == 0x3E:
            # 3E 80(suppress)는 응답이 없는 것이 정상. 횟수만 센다.
            tester_present += 1
            continue
        if tx.service == 0x10:
            sub = tx.request[1] & 0x7F if len(tx.request) > 1 else None
            sessions.append({
                "ecu": ecu, "sub": sub, "ok": tx.positive,
                "nrc": tx.negative_code, "nrc_label": describe_nrc(tx.negative_code),
                "expects_response": tx.expects_response,
            })
            continue
        if tx.service != 0x27:
            # 보안 때문에 거절된 다른 서비스
            if tx.negative_code in (0x33, 0x35, 0x36, 0x37):
                locked.add(ecu)
                events.append({
                    "ecu": ecu, "service": tx.service, "kind": "protected",
                    "ok": False, "nrc": tx.negative_code,
                    "nrc_label": describe_nrc(tx.negative_code),
                    "request_len": len(tx.request),
                })
            continue
        level = tx.request[1] if len(tx.request) > 1 else None
        kind = "seed_or_cert_request" if level is not None and level % 2 == 1 else "key_or_cert_response"
        # 41/42는 홀수/짝수이므로 위 규칙과 맞다.
        event = {
            "ecu": ecu, "service": 0x27, "level": level, "kind": kind,
            "ok": tx.positive, "nrc": tx.negative_code,
            "nrc_label": describe_nrc(tx.negative_code),
            "request_len": len(tx.request),
            "response_len": len(tx.response) if tx.response else 0,
        }
        events.append(event)
        if tx.negative_code in (0x33, 0x35, 0x36, 0x37):
            locked.add(ecu)
        if tx.positive and level is not None and level % 2 == 0:
            unlocked.add(ecu)
            locked.discard(ecu)

    return {
        "enabled": True,
        "events": events,
        "locked_ecus": sorted(locked),
        "unlocked_ecus": sorted(unlocked),
        "sessions": sessions,
        "tester_present": tester_present,
        "unlock_send_enabled": unlock_allowed(),
        "note": "실송신은 SCAN_SECURITY_UNLOCK과 정당한 보안 자료가 필요합니다.",
    }
