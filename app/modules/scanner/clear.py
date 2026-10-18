"""고장코드 지우기(2026-10-18 대표 결정으로 웹·앱 허용). 읽기 스캔과 따로, 저장한 스캔(지우기 전 기록)에서만 시작한다.

흐름: 권한 확인 → 확인 창(차량번호 입력) → 지우기 계획 발급(1회용, 감사기록) → 사전 점검(차속 0) →
제어기별 14 FF FF FF(NRC 78이면 최대 6회 대기·재시도, NRC 7F면 10 03 → 14 → 10 01) →
실패한 제어기가 있거나 OBD 고장코드가 있었으면 04 → 2초 뒤 다시 읽기 → 결과 저장(dtc_clear_logs, 감사기록).

이 모듈은 DB를 쓰지 않는 계획·판정 함수만 둔다. 저장·권한·화면은 routes·service가 맡는다.
위카 앱 dev(ble_connect_service.dart clearDtc, e118ae4)와 다른 점: 14 FF FF FF(3바이트 그룹, main의 5바이트 오류 아님),
10 03은 NRC 7F일 때만, 대상은 지우기 전 스캔에서 응답한 모든 제어기 ∪ 앱의 고정 6개(2026-10-18 대표 결정).
"""

from app.modules.scanner import obd

# 위카 앱 dev clearDtc의 대상(파워트레인, 섀시·ABS, 섀시, ESC, BCM, 게이트웨이)
BASE_TARGETS = ("7E0", "7D2", "7D0", "7D6", "7B2", "770")
CLEAR_COMMAND = "14FFFFFF"
OBD_CLEAR = "04"
PENDING_RETRIES = 6
CLEAR_TIMEOUT_MS = 3000
VERIFY_DELAY_MS = 2000
SESSION_COMMANDS = ("1003", "1001")
# 지우기 결과로 받을 수 있는 명령. 이 밖의 명령이 오면 결과를 받지 않는다.
ALLOWED_COMMANDS = {"ATRV", "010D", "010C", CLEAR_COMMAND, OBD_CLEAR, "0101", "03", "07", "0A", "190209", "1902FF",
                    *SESSION_COMMANDS}
NRC_NOT_IN_SESSION = 0x7F
NRC_LABELS = {0x22: "조건 불충족(시동·차속 확인)", 0x31: "범위 밖", 0x33: "보안 잠금", 0x72: "쓰기 실패",
              0x7F: "현재 세션에서 지원 안 함", 0x11: "지원 안 함", 0x13: "길이 오류", 0x78: "응답 대기"}


def _request_of(address: str) -> str | None:
    if len(address) == 8 and address.startswith("18DAF1"):
        return f"18DA{address[6:]}F1"
    if len(address) == 3:
        return f"{int(address, 16) - 8:03X}"
    return None


def _responded(row: dict) -> bool:
    """읽기 스캔 단계 결과에서 그 제어기가 답했는지(긍정, 부정 NRC, 응답 대기)."""
    status = row.get("status")
    return status in ("ok", "negative", "pending") or (status == "unsupported" and "NRC" in str(row.get("message")))


def clear_targets(result: dict) -> list[str]:
    """2026-10-18 대표 결정: 지우기 전 스캔(제어기 순회 포함)에서 응답한 모든 제어기 ∪ 앱 dev 고정 6개.

    순서: 고장코드가 나온 제어기 → 응답한 제어기(긍정 응답 ECU 목록, 부정·대기 응답 단계) → 고정 6개.
    29비트 차량은 고정 6개(11비트)를 넣지 않는다. K-Line 주소는 물리 요청 주소가 없어 넣지 않는다.
    """
    found: list[str] = []

    def add(header: str | None) -> None:
        if header and header not in found:
            found.append(header)

    for dtc in result.get("dtcs") or []:
        add(_request_of(str(dtc.get("ecu") or "").upper()))
    for ecu in result.get("ecus") or []:
        add(_request_of(str(ecu.get("address") or "").upper()))
    for row in result.get("steps") or []:
        header = str(row.get("header") or "").upper()
        if header and _responded(row) and (len(header) == 3 or header.startswith("18DA")):
            add(header)
    if (result.get("protocol") or {}).get("bus") == "can29":
        return found
    return found + [h for h in BASE_TARGETS if h not in found]


def has_obd_dtcs(result: dict) -> bool:
    return any(str(d.get("source") or "").startswith("OBD") for d in result.get("dtcs") or [])


def build_clear_plan(result: dict) -> dict:
    """steps는 읽기 계획과 같은 형식. 추가 필드: pending_retries, session_fallback, delay_ms, when.clear_fallback."""
    steps: list[dict] = []

    def add(group: str, label: str, command: str, **extra) -> None:
        steps.append({"id": len(steps) + 1, "group": group, "label": label, "command": command,
                      "header": None, "timeout": 2000, "optional": True, "probe": False, "bus": None} | extra)

    add("clear_check", "배터리 전압(단말기 측정)", "ATRV")
    add("clear_check", "차속(0이어야 지움)", "010D")
    add("clear_check", "엔진 회전수(시동 꺼짐 권장)", "010C")
    targets = clear_targets(result)
    for header in targets:
        add("clear", f"{header} 고장코드 지우기(14 FF FF FF)", CLEAR_COMMAND, header=header,
            timeout=CLEAR_TIMEOUT_MS, bus="can", pending_retries=PENDING_RETRIES, session_fallback=True)
    add("clear", "OBD 고장코드 지우기(04)", OBD_CLEAR, timeout=5000, pending_retries=PENDING_RETRIES,
        when={"clear_fallback": True, "obd_dtcs": has_obd_dtcs(result)})
    add("clear_verify", "다시 읽기: 경고등·고장코드 수", "0101", delay_ms=VERIFY_DELAY_MS)
    add("clear_verify", "다시 읽기: 확정 고장코드", "03")
    add("clear_verify", "다시 읽기: 대기 고장코드", "07")
    add("clear_verify", "다시 읽기: 영구 고장코드", "0A")
    add("clear_verify", "다시 읽기: 전체 제어기(19 02 09)", "190209", timeout=CLEAR_TIMEOUT_MS, bus="can")
    for header in targets:
        add("clear_verify", f"다시 읽기: {header} 고장코드(19 02)", "1902FF", header=header,
            timeout=CLEAR_TIMEOUT_MS, bus="can")
    return {"steps": steps, "targets": targets}


def validate_results(steps: list[dict], issued: list[str]) -> str | None:
    """지우기 결과 단계 검사. 발급한 대상 밖의 주소나 허용 밖의 명령이 있으면 그 이유."""
    allowed_headers = set(issued) | {None}
    for step in steps:
        command = str(step.get("command") or "").replace(" ", "").upper()
        if command not in ALLOWED_COMMANDS:
            return f"지우기 결과에 허용하지 않는 명령이 있습니다: {command[:20]}"
        if step.get("header") not in allowed_headers:
            return f"발급하지 않은 제어기 주소입니다: {step.get('header')}"
    return None


def _speed(reply: str | None, bus: str | None) -> int | None:
    outcome = obd.evaluate("010D", reply, bus)
    for payloads in outcome.positive.values():
        for payload in payloads:
            if len(payload) >= 3:
                return payload[2]
    return None


def precheck(steps: list[dict], bus: str | None) -> dict:
    speed = next((_speed(s.get("reply"), bus) for s in steps if s.get("command") == "010D"), None)
    return {"speed": speed, "moving": bool(speed)}


def _ecu_result(step: dict, bus: str | None) -> dict:
    reply = step.get("reply")
    header = step.get("header")
    session_used = "50 03" in (reply or "").upper() or "5003" in (reply or "").replace(" ", "").upper()
    if step.get("error") == "skipped":
        return {"header": header, "status": "skipped", "nrc": None, "session_used": False,
                "message": step.get("reason") or "건너뜀"}
    outcome = obd.evaluate(CLEAR_COMMAND, reply, bus, step.get("error"))
    if outcome.positive:
        status, nrc, message = "cleared", None, "지움(54)"
    elif outcome.negative:
        nrc = next(iter(outcome.negative.values()))
        status, message = "rejected", f"거부 NRC {nrc:02X} {NRC_LABELS.get(nrc, '')}".strip()
    elif outcome.status == "pending":
        status, nrc, message = "pending", 0x78, "응답 대기(NRC 78)만 받고 끝나지 않음"
    else:
        status, nrc, message = "no_response", None, outcome.message or "응답 없음"
    return {"header": header, "status": status, "nrc": nrc, "session_used": session_used, "message": message}


def _dtcs(steps: list[dict], bus: str | None) -> list[str]:
    codes: list[str] = []
    for step in steps:
        command = str(step.get("command") or "").upper()
        if step.get("group") != "clear_verify" or command not in ("03", "07", "0A", "190209", "1902FF"):
            continue
        outcome = obd.evaluate(command, step.get("reply"), bus, step.get("error"))
        for payloads in outcome.positive.values():
            if command in ("03", "07", "0A"):
                found = obd.obd_dtcs(payloads, bus)
            else:
                found = [d["code"] for p in payloads for d in obd.uds_dtcs(p)]
            codes += [c for c in found if c not in codes]
    return codes


def _short(code: str) -> str:
    return code[:5]


def evaluate_clear(steps: list[dict], bus: str | None, dtcs_before: list[str]) -> dict:
    """지우기 결과: 제어기별 결과, 04 결과, 다시 읽은 고장코드와 전후 비교, 전체 상태."""
    check = precheck(steps, bus)
    ecus = [_ecu_result(s, bus) for s in steps if s.get("group") == "clear" and s.get("command") == CLEAR_COMMAND]
    obd04 = next((s for s in steps if s.get("command") == OBD_CLEAR), None)
    obd04_result = None
    if obd04 is not None:
        if obd04.get("error") == "skipped":
            obd04_result = {"status": "skipped", "message": obd04.get("reason")}
        else:
            outcome = obd.evaluate(OBD_CLEAR, obd04.get("reply"), bus, obd04.get("error"))
            obd04_result = {"status": "cleared" if outcome.positive else outcome.status, "message": outcome.message}
    after = _dtcs(steps, bus)
    before_short = {_short(c) for c in dtcs_before}
    after_short = {_short(c) for c in after}
    sent = [e for e in ecus if e["status"] != "skipped"]
    cleared_any = any(e["status"] == "cleared" for e in ecus) or (obd04_result or {}).get("status") == "cleared"
    if check["moving"]:
        status = "aborted"
    elif not cleared_any:
        status = "failed"
    elif after or any(e["status"] != "cleared" for e in sent):
        status = "partial"
    else:
        status = "ok"
    return {
        "status": status, "precheck": check, "ecus": ecus, "obd04": obd04_result,
        "dtcs_before": list(dtcs_before), "dtcs_after": after,
        "cleared": sorted(c for c in dtcs_before if _short(c) not in after_short),
        "remaining": sorted(c for c in after if _short(c) in before_short),
        "new": sorted(c for c in after if _short(c) not in before_short),
        "session_used": [e["header"] for e in ecus if e["session_used"]],
    }
