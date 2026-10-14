"""CAN 분석에서 쓰는 외부 AI 호출(결과지 판독, 보고서 요약).

관리자 'AI 연결'에서 'CAN 분석' 용도를 켠 연결만 쓴다. 키는 호출 순간에만 복호화한다.
"""

import base64
import json
import re

import httpx
from flask import current_app
from sqlalchemy import select

from app.core.crypto import decrypt
from app.core.errors import ServiceError
from app.extensions import db
from app.modules.admin.models import AiConnection, AiProvider, AiStatus

FEATURE = "canlab"
PROVIDER_ORDER = (AiProvider.OPENAI, AiProvider.ANTHROPIC, AiProvider.GEMINI)


def available_connection() -> AiConnection | None:
    """연결 테스트를 통과했고 CAN 분석 용도를 켠 연결. 여러 개면 OpenAI → Anthropic → Gemini 순."""
    rows = db.session.scalars(select(AiConnection).where(AiConnection.status == AiStatus.OK)).all()
    usable = {c.provider: c for c in rows if c.has_key and (c.features or {}).get(FEATURE)}
    return next((usable[p] for p in PROVIDER_ORDER if p in usable), None)


def _request(connection: AiConnection, system: str, prompt: str, image: tuple[str, bytes] | None) -> str:
    key = decrypt(connection.key_enc)
    timeout = current_app.config["AI_REQUEST_TIMEOUT_SECONDS"]
    encoded = base64.b64encode(image[1]).decode() if image else None
    if connection.provider == AiProvider.OPENAI:
        content: list[dict] = [{"type": "text", "text": prompt}]
        if image:
            content.append({"type": "image_url", "image_url": {"url": f"data:{image[0]};base64,{encoded}"}})
        response = httpx.post(
            "https://api.openai.com/v1/chat/completions", timeout=timeout,
            headers={"Authorization": f"Bearer {key}"},
            json={"model": connection.model,
                  "messages": [{"role": "system", "content": system}, {"role": "user", "content": content}]},
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]
    if connection.provider == AiProvider.ANTHROPIC:
        content = [{"type": "text", "text": prompt}]
        if image:
            content.insert(0, {"type": "image", "source": {"type": "base64", "media_type": image[0], "data": encoded}})
        response = httpx.post(
            "https://api.anthropic.com/v1/messages", timeout=timeout,
            headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
            json={"model": connection.model, "max_tokens": 4000, "system": system,
                  "messages": [{"role": "user", "content": content}]},
        )
        response.raise_for_status()
        return "".join(part.get("text", "") for part in response.json()["content"])
    parts: list[dict] = [{"text": prompt}]
    if image:
        parts.append({"inline_data": {"mime_type": image[0], "data": encoded}})
    response = httpx.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{connection.model}:generateContent",
        timeout=timeout, headers={"x-goog-api-key": key},
        json={"systemInstruction": {"parts": [{"text": system}]}, "contents": [{"parts": parts}]},
    )
    response.raise_for_status()
    return "".join(p.get("text", "") for p in response.json()["candidates"][0]["content"]["parts"])


def ask(system: str, prompt: str, image: tuple[str, bytes] | None = None) -> tuple[str, str]:
    """(답변, 공급자)를 돌려준다. 실패하면 이유를 한글로 알린다."""
    connection = available_connection()
    if connection is None:
        raise ServiceError("사용할 AI 연결이 없습니다. 설정 > AI 연결에서 키를 등록·테스트하고 "
                           "'CAN 분석' 용도를 켜세요.")
    try:
        return _request(connection, system, prompt, image), connection.provider
    except httpx.TimeoutException as exc:
        raise ServiceError("AI 응답 시간이 초과되었습니다. 잠시 후 다시 시도하세요.", 504) from exc
    except httpx.HTTPStatusError as exc:
        raise ServiceError(f"AI 공급자가 오류를 반환했습니다(HTTP {exc.response.status_code}).", 502) from exc
    except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
        raise ServiceError("AI 응답을 처리하지 못했습니다.", 502) from exc


OCR_SYSTEM = (
    "너는 자동차 진단기 결과지 판독기다. 이미지 표의 각 행을 그대로 옮긴다. 값을 추측하거나 계산하지 않는다. "
    "읽을 수 없는 칸은 건너뛴다."
)
OCR_PROMPT = (
    "이 G-Scan 진단 결과지 페이지의 센서 표를 JSON 배열로만 답하라. "
    '각 원소는 {"label": 센서명 원문, "value": 센서값 원문 문자열, "unit": 단위 원문 또는 ""} 이다. '
    "제목, 날짜, 페이지 번호, 차량정보(VIN·차량번호)는 넣지 않는다."
)


def read_table(image: tuple[str, bytes] | None = None, page_text: str | None = None) -> tuple[list[dict], str]:
    """결과지 한 페이지(그림 또는 PDF 글자)를 표 행 목록으로 바꾼다."""
    prompt = OCR_PROMPT if image else f"{OCR_PROMPT}\n\n페이지 글자:\n{(page_text or '')[:20000]}"
    text, provider = ask(OCR_SYSTEM, prompt, image)
    match = re.search(r"\[.*\]", text, re.DOTALL)
    try:
        rows = json.loads(match.group(0)) if match else []
    except json.JSONDecodeError:
        rows = []
    if not isinstance(rows, list):
        rows = []
    cleaned = [
        {"label": str(r.get("label", "")).strip()[:200], "value": str(r.get("value", "")).strip()[:50],
         "unit": str(r.get("unit", "")).strip()[:20]}
        for r in rows if isinstance(r, dict) and str(r.get("label", "")).strip()
    ]
    if not cleaned:
        raise ServiceError("AI가 표를 읽지 못했습니다. 값을 직접 입력하세요.", 502)
    return cleaned, provider


REPORT_SYSTEM = (
    "너는 전기차·하이브리드 고전압 배터리 진단 보고서를 쓰는 정비 전문가다. 주어진 측정값과 판정 근거만 사용하고 "
    "없는 값을 지어내지 않는다. 확정되지 않은 수식(가설)으로 계산된 값은 그렇다고 밝힌다. 한국어 존댓말로 쓴다."
)


def summarize_report(facts: dict) -> tuple[str, str]:
    prompt = (
        "다음 진단 데이터로 고객용 결과 요약을 써라. 형식: 1) 종합 의견 2~3문장 2) 배터리 상태 항목별 해석 "
        "3) 고장코드 해석 4) 권장 조치. 마크다운 제목 없이 번호 목록으로 쓴다.\n\n"
        + json.dumps(facts, ensure_ascii=False)
    )
    return ask(REPORT_SYSTEM, prompt)
