from flask import current_app, g

from app.core.time import iso
from app.core.validation import validate
from app.extensions import limiter
from app.modules.accounts import service
from app.modules.api import bp
from app.modules.api.auth import current_user, require_api_auth
from app.modules.api.http import api_input, respond
from app.modules.api.serializers import company_dict, user_dict


def _login_limit() -> str:
    return current_app.config["API_LOGIN_RATE_LIMIT"]


@bp.post("/auth/login")
@limiter.limit(_login_limit)
def login():
    data = validate(
        api_input(),
        {"tid": ["required", "string"], "password": ["required", "string"]},
        {"tid.required": "아이디를 입력해주세요.", "password.required": "비밀번호를 입력해주세요."},
    )
    user, pair = service.login(data["tid"], data["password"])
    return respond({**pair, "user": user_dict(user)})


@bp.post("/auth/refresh")
def refresh():
    return respond(service.refresh(api_input().get("refresh_token")))


@bp.post("/auth/logout")
@require_api_auth
def logout():
    service.logout(current_user(), g.get("jwt_payload"), api_input().get("refresh_token"))
    return respond({"message": "로그아웃되었습니다."})


@bp.get("/auth/me")
@require_api_auth
def me():
    return respond({"user": user_dict(current_user())})


@bp.post("/auth/invalidateAllTokens")
@require_api_auth
def invalidate_all_tokens():
    return respond(service.reissue_after_invalidation(current_user()))


@bp.post("/auth/companyCode")
def company_code():
    return respond(company_dict(service.company_by_code(api_input().get("company_code"))))


@bp.post("/auth/register")
@limiter.limit(_login_limit)
def register():
    service.register(api_input())
    return respond({"message": "회원가입이 완료되었습니다."}, 201)


@bp.post("/auth/registerValidate")
def register_validate():
    service.validate_registration_fields(api_input())
    return respond({"message": "모든 입력값이 유효합니다."})


@bp.post("/auth/requestSms")
@limiter.limit(_login_limit)
def request_sms():
    data = validate(
        api_input(),
        {
            "mobile": ["required", "string"],
            "sms_code_key": ["required", "string"],
            "tid": ["nullable", "string"],
        },
    )
    service.request_sms(data["mobile"], data["sms_code_key"], data.get("tid"))
    return respond({"message": "휴대폰 인증번호가 발송되었습니다"})


@bp.post("/auth/verifySms")
@limiter.limit(_login_limit)
def verify_sms():
    data = api_input()
    if service.verify_sms(data.get("mobile"), data.get("sms_code"), data.get("sms_code_key")):
        return respond({"message": "휴대폰 인증번호가 확인되었습니다"})
    return respond({"message": "인증번호가 일치하지 않습니다."}, 400)


@bp.post("/auth/findTid")
@limiter.limit(_login_limit)
def find_tid():
    user = service.find_tid(api_input().get("mobile"))
    return respond(
        {
            "message": "아이디가 찾아졌습니다",
            "created_at": iso(user.created_at),
            "masked_tid": service.mask_tid(user.tid),
        }
    )


@bp.post("/auth/setPasswordByVerifySms")
@limiter.limit(_login_limit)
def set_password_by_verify_sms():
    return respond(service.reset_password_by_sms(api_input()))


@bp.post("/auth/setMobile")
@require_api_auth
def set_mobile():
    return respond(service.set_mobile(current_user(), api_input()))


@bp.post("/auth/setPassword")
@require_api_auth
def set_password():
    return respond(service.change_password(current_user(), api_input()))


@bp.post("/auth/withdraw")
@require_api_auth
def withdraw():
    service.withdraw(current_user(), api_input().get("message"))
    return respond({"message": "탈퇴가 완료되었습니다."})
