"""LTE 단말기 API. 모바일 앱 API(Laravel 호환)와 따로, 'Authorization: Device <토큰>'으로 인증한다."""

from flask import request

from app.modules.api import bp
from app.modules.api.http import api_input, respond
from app.modules.obd import telematics


@bp.get("/telematics/plan")
def telematics_plan():
    device = telematics.authenticate(request.headers.get("Authorization"))
    return respond(telematics.plan_for(device, api_input().get("car_no")))


@bp.post("/telematics/captures")
def telematics_capture():
    device = telematics.authenticate(request.headers.get("Authorization"))
    scan = telematics.receive(device, api_input())
    data = scan.bms_data
    return respond({"id": scan.id, "status": data["status"], "errors": data["errors"]}, 201)
