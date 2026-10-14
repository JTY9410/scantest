import re
from collections.abc import Callable

from flask_wtf import FlaskForm
from wtforms import BooleanField, HiddenField, IntegerField, SelectField, StringField, TextAreaField
from wtforms.validators import DataRequired, Length, NumberRange, Optional, ValidationError

from app.modules.obd.models import CAN_BITRATES, ObdDialect, ObdTransport
from app.modules.obd.service import (
    ADAPTER_COMMAND_PATTERN,
    HEADER_PATTERN,
    MAX_COMMANDS,
    READ_COMMAND_PATTERN,
    UUID_PATTERN,
    command_lines,
)


def _matches(pattern: re.Pattern, message: str, transform: Callable[[str], str] = str.strip):
    def check(form, field):
        value = (field.data or "").strip()
        if value and not pattern.fullmatch(transform(value)):
            raise ValidationError(message)

    return check


def _command_lines(pattern: re.Pattern, message: str):
    def check(form, field):
        lines = command_lines(field.data)
        if len(lines) > MAX_COMMANDS:
            raise ValidationError(f"최대 {MAX_COMMANDS}줄까지 입력할 수 있습니다.")
        wrong = next((line for line in lines if not pattern.fullmatch(line)), None)
        if wrong:
            raise ValidationError(f"{message} 확인할 줄: {wrong}")

    return check


_uuid = _matches(UUID_PATTERN, "FFF0 같은 4자리 또는 128비트 UUID 형식으로 입력하세요.")
_header = _matches(HEADER_PATTERN, "7E4 같은 3자리 또는 18DA10F1 같은 8자리 16진수로 입력하세요.",
                   str.upper)


class ObdProfileForm(FlaskForm):
    name = StringField("프로필 이름", validators=[DataRequired("프로필 이름을 입력하세요."), Length(max=100)])
    transport = SelectField("연결 방식", choices=[(t.value, t.label) for t in ObdTransport])
    dialect = SelectField("명령 체계", choices=[(d.value, d.label) for d in ObdDialect], default=ObdDialect.ELM327)
    can_bitrate = SelectField("CAN 속도(slcan)", coerce=int, default=0, filters=[lambda v: v or 0],
                              choices=[(0, "자동 감지")] + [(b, f"{b // 1000} kbit/s") for b in CAN_BITRATES])
    device_name_prefix = StringField(
        "기기 이름 접두사",
        validators=[DataRequired("기기 이름 접두사를 입력하세요."), Length(max=50)],
    )
    service_uuid = StringField("서비스 UUID", validators=[Optional(), _uuid])
    write_uuid = StringField("쓰기 특성 UUID", validators=[Optional(), _uuid])
    notify_uuid = StringField("알림 특성 UUID", validators=[Optional(), _uuid])
    init_commands = TextAreaField(
        "어댑터 초기화 명령",
        validators=[_command_lines(ADAPTER_COMMAND_PATTERN,
                                   "AT 또는 ST로 시작하는 어댑터 명령만 한 줄에 하나씩 입력하세요.")],
    )
    request_header = StringField("요청 헤더(CAN ID)", validators=[Optional(), _header])
    response_header = StringField("응답 헤더(CAN ID)", validators=[Optional(), _header])
    read_commands = TextAreaField(
        "조회 명령",
        validators=[_command_lines(READ_COMMAND_PATTERN,
                                   "16진수 바이트(예: 220101)만 한 줄에 하나씩 입력하세요.")],
    )
    response_timeout_ms = IntegerField(
        "응답 대기 시간(ms)",
        default=2000,
        validators=[DataRequired("응답 대기 시간을 입력하세요."),
                    NumberRange(100, 10000, "100~10000 사이로 입력하세요.")],
    )
    enabled = BooleanField("앱에 제공", default=True)
    version = HiddenField()

    def validate(self, extra_validators=None) -> bool:
        valid = super().validate(extra_validators)
        uuids = (self.service_uuid, self.write_uuid, self.notify_uuid)
        if self.transport.data == ObdTransport.BLE and not all((f.data or "").strip() for f in uuids):
            self.service_uuid.errors.append("BLE 연결에는 서비스·쓰기·알림 UUID가 모두 필요합니다.")
            valid = False
        if self.dialect.data == ObdDialect.SLCAN and command_lines(self.init_commands.data):
            self.init_commands.errors.append("slcan 진단기는 AT·ST 초기화 명령을 받지 않습니다. 비워 두세요.")
            valid = False
        headers = [(f.data or "").strip() for f in (self.request_header, self.response_header)]
        if any(headers) and not all(headers):
            self.request_header.errors.append("요청·응답 헤더는 함께 입력하세요.")
            valid = False
        return valid


class TelematicsDeviceForm(FlaskForm):
    serial = StringField("단말기 일련번호", validators=[DataRequired("일련번호를 입력하세요."), Length(4, 64)])
    name = StringField("이름", validators=[Optional(), Length(max=100)])
    company_id = SelectField("소속 회사", coerce=int, default=0)
