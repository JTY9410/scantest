"""외부 차량정보 조회(위카 진단 서버) 연동."""

from typing import Any

import httpx
from flask import current_app

from app.core import audit
from app.core.errors import ServiceError
from app.extensions import db
from app.modules.accounts.models import User


def fetch_car_info(user: User, car_no: str | None) -> Any:
    if not car_no:
        raise ServiceError("차량번호를 입력해주세요.")
    url = current_app.config.get("CAR_INFO_API_URL")
    key = current_app.config.get("CAR_INFO_API_KEY")
    if not url or not key:
        raise ServiceError("차량정보 조회 설정이 되어 있지 않습니다. 관리자에게 문의하세요.", 503)

    try:
        response = httpx.post(
            url,
            data={"authkey": key, "car_no": car_no},
            timeout=current_app.config["CAR_INFO_TIMEOUT_SECONDS"],
        )
        body = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        current_app.logger.warning("차량정보 조회 실패: %s", type(exc).__name__)
        raise ServiceError("차량정보 조회 서버에 연결할 수 없습니다.", 502) from exc

    audit.record(
        "Scan: Get Car Info",
        "Scan",
        user_id=user.id,
        changes={"request": {"car_no": car_no}, "response": body},
    )
    db.session.commit()

    if not isinstance(body, dict) or body.get("status") != "ok":
        message = body.get("msg") if isinstance(body, dict) else None
        raise ServiceError(message or "차량정보를 찾을 수 없습니다.", 400, response=body)
    return body.get("dto")
