"""스캔 실패·무응답 단계에 대한 AI(또는 규칙) 검증 초안.

DB를 바꾸지 않는다. 결과는 scan.bms_data['ai_verify']에만 붙인다.
OEM DTC 의미를 지어내지 않고, 관측된 오류·공개 코드 설명만 쓴다.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm.attributes import flag_modified

from app.core import audit
from app.core.errors import ServiceError
from app.extensions import db
from app.modules.canlab import ai as canlab_ai
from app.modules.accounts.models import User
from app.modules.scans.models import Scan
from app.modules.scanner.service import scan_result

VERIFY_SYSTEM = (
    "너는 자동차 OBD/UDS 스캔 통신 점검 도우미다. "
    "주어진 실패·무응답 단계만 보고, 원인 가설과 재시도 제안을 한국어로 짧게 쓴다. "
    "고장코드의 OEM 전용 의미를 추측하거나 지어내지 않는다. "
    "공개 표준·입력에 있는 설명만 인용한다. "
    "JSON만 답한다: "
    '{"summary":"한 줄 요약","items":[{"command":"…","issue":"…","suggestion":"…"}],'
    '"retry":["재시도 제안1"]}.'
)


def _failed_steps(result: dict) -> list[dict]:
    steps = result.get("steps") if isinstance(result.get("steps"), list) else []
    out = []
    for step in steps:
        if not isinstance(step, dict):
            continue
        err = step.get("error")
        if not err or err == "skipped":
            continue
        out.append({
            "header": step.get("header"),
            "command": step.get("command"),
            "label": step.get("label"),
            "error": err,
            "reason": step.get("reason"),
            "reply": (step.get("reply") or "")[:400],
            "tMs": step.get("tMs"),
        })
    return out[:40]


def _rule_fallback(failed: list[dict], errors: list[dict]) -> dict[str, Any]:
    items = []
    for step in failed:
        err = str(step.get("error") or "")
        if err == "timeout":
            issue, suggestion = "응답 시간 초과(무응답)", "시동 ON·단자 접촉·진단기 전원을 확인한 뒤 같은 명령을 다시 보내세요."
        elif err == "disconnected":
            issue, suggestion = "진단기 연결 끊김", "블루투스/USB를 다시 연결한 뒤 스캔을 재개하세요."
        elif "NRC" in err.upper() or "7F" in (step.get("reply") or "").upper():
            issue, suggestion = "부정 응답(NRC) 가능", "읽기 세션에서만 허용된 명령인지 확인하고, 지우기·쓰기 명령은 쓰지 마세요."
        else:
            issue, suggestion = f"통신 오류: {err}", "로그의 원문 응답을 확인한 뒤 동일 조건에서 재스캔하세요."
        items.append({
            "command": f"{step.get('header') or ''} {step.get('command') or ''}".strip(),
            "issue": issue,
            "suggestion": suggestion,
        })
    if not items and errors:
        for e in errors[:10]:
            if not isinstance(e, dict):
                continue
            items.append({
                "command": f"{e.get('header') or ''} {e.get('command') or ''}".strip(),
                "issue": e.get("message") or e.get("label") or "오류",
                "suggestion": "결과 화면의 오류 기록을 확인하세요.",
            })
    summary = (
        f"통신 문제 {len(items)}건을 규칙으로 정리했습니다. AI 연결이 없어 자동 설명은 생략했습니다."
        if items else "검증할 통신 실패가 없습니다."
    )
    return {
        "summary": summary,
        "items": items,
        "retry": ["시동 ON 유지", "진단기 재연결 후 스캔하기", "연속 무응답 시 다른 진단기·케이블 시험"],
        "source": "rules",
        "provider": None,
    }


def verify_scan(actor: User, scan: Scan) -> dict[str, Any]:
    """스캔 결과의 실패 단계를 검증하고 bms_data['ai_verify']에 저장한다."""
    result = scan_result(scan)
    failed = _failed_steps(result)
    errors = result.get("errors") if isinstance(result.get("errors"), list) else []
    payload: dict[str, Any]

    if not failed and not errors:
        payload = {
            "summary": "검증할 통신 실패·오류가 없습니다.",
            "items": [],
            "retry": [],
            "source": "rules",
            "provider": None,
        }
    elif canlab_ai.available_connection() is None:
        payload = _rule_fallback(failed, errors)
    else:
        prompt_body = {
            "status": result.get("status"),
            "transport": result.get("transport"),
            "failed_steps": failed,
            "errors": [
                {"group": e.get("group"), "label": e.get("label"), "message": e.get("message"),
                 "command": e.get("command"), "header": e.get("header")}
                for e in errors[:20] if isinstance(e, dict)
            ],
            "dtcs": [
                {"code": d.get("code"), "desc": d.get("desc")}
                for d in (result.get("dtcs") or [])[:20] if isinstance(d, dict)
            ],
        }
        import json
        try:
            text, provider = canlab_ai.ask(VERIFY_SYSTEM, json.dumps(prompt_body, ensure_ascii=False)[:12000])
            parsed = _parse_json(text)
            payload = {
                "summary": str(parsed.get("summary") or "AI 검증을 마쳤습니다."),
                "items": parsed.get("items") if isinstance(parsed.get("items"), list) else [],
                "retry": parsed.get("retry") if isinstance(parsed.get("retry"), list) else [],
                "source": "ai",
                "provider": provider,
            }
        except ServiceError:
            payload = _rule_fallback(failed, errors)
            payload["note"] = "AI 호출에 실패해 규칙 기반 안내로 대체했습니다."

    payload["verified_at"] = datetime.now(UTC).isoformat()
    payload["failed_count"] = len(failed)
    data = dict(scan.bms_data or {})
    data["ai_verify"] = payload
    scan.bms_data = data
    flag_modified(scan, "bms_data")
    audit.record("스캔 AI 검증", "Scan", scan.id, user_id=actor.id,
                 changes={"source": payload.get("source"), "failed": len(failed)})
    db.session.commit()
    return payload


def _parse_json(text: str) -> dict:
    import json
    import re

    text = (text or "").strip()
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", text)
        if not match:
            return {}
        try:
            data = json.loads(match.group(0))
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            return {}
