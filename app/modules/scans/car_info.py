"""외부 차량정보 조회(위카 진단 서버) 연동.

원천 데이터에 일일 조회 한도가 있어, 성공한 조회는 차량번호별로 저장해 다시 쓴다.
앱 API 응답은 Laravel과 같게 원본 dto와 실패 시 400을 유지한다.
"""

import re
from typing import Any

import httpx
from flask import current_app
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core import audit
from app.core.crypto import EncryptionUnavailable, decrypt, encrypt
from app.core.errors import ServiceError
from app.core.time import utcnow
from app.extensions import db
from app.modules.accounts.models import User
from app.modules.scans.models import DEFAULT_CAR_INFO_URL, CarInfoCache, CarInfoSetting

NUMERIC_FIELDS = ("diag_displacement", "diag_capacity", "diag_payload", "diag_new_price", "diag_year",
                  "diag_distance_standard")
GUIDES = {
    "missing": "차량번호를 입력해주세요.",
    "unconfigured": "차량정보 조회 인증키가 없습니다. 설정 > 차량정보 조회에서 등록하세요.",
    "key": "인증키가 올바르지 않습니다. 설정 > 차량정보 조회에서 키를 확인하세요.",
    "not_found": "조회할 수 없는 차량입니다(말소·미등록 또는 상세정보 없음). 차량번호를 확인하세요.",
    "quota": "오늘 조회 한도를 넘었습니다. 내일 다시 시도하세요.",
    "timeout": "차량정보 서버가 응답하지 않습니다(시간 초과). 잠시 뒤 다시 시도하세요.",
    "connection": "차량정보 조회 서버에 연결할 수 없습니다.",
}


class CarInfoError(ServiceError):
    """조회 실패. message는 원천 메시지(앱 호환), guide는 화면 안내 문구."""

    def __init__(self, message: str, status: int, kind: str, **extra: Any):
        super().__init__(message, status, **extra)
        self.kind = kind
        self.guide = GUIDES.get(kind, message)


def normalize_car_no(car_no: str | None) -> str:
    return re.sub(r"\s+", "", car_no or "")


def normalize_dto(dto: dict[str, Any]) -> dict[str, Any]:
    """숫자 필드는 값이 없으면 빈 문자열로 온다. 화면·스캔에서 쓰기 전에 None 또는 숫자로 바꾼다."""
    result = dict(dto)
    for key in NUMERIC_FIELDS:
        value = result.get(key)
        if value in ("", None):
            result[key] = None
        elif isinstance(value, str):
            try:
                result[key] = int(value.replace(",", ""))
            except ValueError:
                result[key] = None
    return result


def get_setting() -> CarInfoSetting | None:
    return db.session.scalar(select(CarInfoSetting).limit(1))


def _credentials() -> tuple[str | None, str | None]:
    setting = get_setting()
    if setting and setting.key_enc:
        try:
            return setting.url, decrypt(setting.key_enc)
        except EncryptionUnavailable as exc:
            raise CarInfoError(str(exc), 503, "unconfigured") from exc
    return current_app.config.get("CAR_INFO_API_URL"), current_app.config.get("CAR_INFO_API_KEY")


def configured() -> bool:
    """조회 주소와 인증키가 (관리자 설정이나 환경변수에) 있는지. 키 값은 읽지 않는다."""
    setting = get_setting()
    if setting and setting.key_enc:
        return bool(setting.url)
    return bool(current_app.config.get("CAR_INFO_API_URL") and current_app.config.get("CAR_INFO_API_KEY"))


def _kind(message: str) -> str:
    if "인증" in message:
        return "key"
    if "일제한" in message or "한도" in message:
        return "quota"
    if "누락" in message:
        return "missing"
    if any(word in message for word in ("말소", "등록되지 않은", "없는 차량", "차량정보 없음")):
        return "not_found"
    return "failed"


def _remember(car_no: str, dto: dict[str, Any]) -> None:
    cache = db.session.scalar(select(CarInfoCache).where(CarInfoCache.car_no == car_no))
    if cache:
        cache.dto, cache.fetched_at = dto, utcnow()
    else:
        db.session.add(CarInfoCache(car_no=car_no, dto=dto, fetched_at=utcnow()))
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()


def lookup(user: User, car_no: str | None, *, refresh: bool = False) -> tuple[dict[str, Any], bool]:
    """(원본 dto, 저장된 결과를 썼는지). refresh면 저장된 결과를 무시하고 다시 조회한다."""
    car_no = normalize_car_no(car_no)
    if not car_no:
        raise CarInfoError(GUIDES["missing"], 400, "missing")
    if not refresh:
        cached = db.session.scalar(select(CarInfoCache).where(CarInfoCache.car_no == car_no))
        if cached:
            return cached.dto, True

    url, key = _credentials()
    if not url or not key:
        raise CarInfoError("차량정보 조회 설정이 되어 있지 않습니다. 관리자에게 문의하세요.", 503, "unconfigured")

    try:
        response = httpx.post(url, data={"authkey": key, "car_no": car_no},
                              timeout=current_app.config["CAR_INFO_TIMEOUT_SECONDS"])
        body = response.json()
    except httpx.TimeoutException as exc:
        current_app.logger.warning("차량정보 조회 시간 초과")
        raise CarInfoError(GUIDES["timeout"], 502, "timeout") from exc
    except (httpx.HTTPError, ValueError) as exc:
        current_app.logger.warning("차량정보 조회 실패: %s", type(exc).__name__)
        raise CarInfoError(GUIDES["connection"], 502, "connection") from exc

    audit.record("Scan: Get Car Info", "Scan", user_id=user.id,
                 changes={"request": {"car_no": car_no}, "response": body})
    db.session.commit()

    if not isinstance(body, dict) or body.get("status") != "ok" or not isinstance(body.get("dto"), dict):
        message = (body.get("msg") if isinstance(body, dict) else None) or "차량정보를 찾을 수 없습니다."
        raise CarInfoError(message, 400, _kind(message), response=body)
    _remember(car_no, body["dto"])
    return body["dto"], False


def fetch_car_info(user: User, car_no: str | None) -> Any:
    return lookup(user, car_no)[0]


# ---- 관리자 설정 ---------------------------------------------------------------

def _setting_for_update(version: int | None) -> CarInfoSetting:
    setting = get_setting()
    if setting is None:
        setting = CarInfoSetting(url=DEFAULT_CAR_INFO_URL)
        db.session.add(setting)
    elif version is not None and version != setting.version:
        raise ServiceError("다른 관리자가 먼저 바꿨습니다. 새로고침 후 다시 시도하세요.", 409)
    return setting


def save_url(actor: User, url: str, version: int | None) -> CarInfoSetting:
    url = (url or "").strip()
    if not url.startswith("https://"):
        raise ServiceError("주소는 https://로 시작해야 합니다.")
    setting = _setting_for_update(version)
    setting.url = url
    db.session.flush()
    audit.record("차량정보 조회 주소 변경", "CarInfoSetting", setting.id, user_id=actor.id,
                 changes={"url": url})
    db.session.commit()
    return setting


def replace_key(actor: User, api_key: str) -> CarInfoSetting:
    api_key = (api_key or "").strip()
    if len(api_key) < 4:
        raise ServiceError("인증키를 확인하세요.")
    setting = _setting_for_update(None)
    had_key = setting.has_key
    setting.key_enc = encrypt(api_key)
    setting.key_last4 = api_key[-4:]
    setting.last_test_message = None
    db.session.flush()
    audit.record("차량정보 인증키 교체" if had_key else "차량정보 인증키 등록", "CarInfoSetting", setting.id,
                 user_id=actor.id, changes={"key_last4": setting.key_last4})
    db.session.commit()
    return setting


def revoke_key(actor: User) -> None:
    setting = get_setting()
    if setting is None or not setting.has_key:
        raise ServiceError("등록된 인증키가 없습니다.")
    setting.key_enc = None
    setting.key_last4 = None
    audit.record("차량정보 인증키 폐기", "CarInfoSetting", setting.id, user_id=actor.id)
    db.session.commit()


def test_lookup(actor: User, car_no: str) -> tuple[bool, str, dict[str, Any] | None]:
    """키 확인용 실제 조회. 저장된 결과를 쓰지 않는다."""
    setting = _setting_for_update(None)
    try:
        dto, _ = lookup(actor, car_no, refresh=True)
    except CarInfoError as error:
        ok, message, dto = False, f"{error.guide} (원문: {error.message})", None
    else:
        ok, message = True, f"조회 성공: {dto.get('diag_company', '')} {dto.get('diag_model', '')}".strip()
    setting = get_setting() or setting
    setting.last_tested_at = utcnow()
    setting.last_test_message = message[:500]
    db.session.commit()
    return ok, message, dto


def recent_cache(limit: int = 10) -> list[CarInfoCache]:
    return list(db.session.scalars(select(CarInfoCache).order_by(CarInfoCache.fetched_at.desc()).limit(limit)))
