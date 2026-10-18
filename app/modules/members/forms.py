from flask_wtf import FlaskForm
from wtforms import BooleanField, EmailField, HiddenField, SelectField, StringField
from wtforms.validators import DataRequired, Email, Length, Optional, Regexp

from app.modules.accounts.models import UserType


class MemberEditForm(FlaskForm):
    name = StringField("이름", validators=[DataRequired("이름을 입력하세요."), Length(max=255)])
    type = SelectField("유형", choices=[(t.value, t.label) for t in UserType])
    company_id = SelectField("소속 회사", coerce=int, choices=[(0, "소속 없음")])
    mobile = StringField(
        "휴대전화",
        validators=[
            Optional(),
            Regexp(r"^01[0-9]-?[0-9]{3,4}-?[0-9]{4}$", message="010-1234-5678 형식으로 입력하세요."),
        ],
    )
    email = EmailField(
        "이메일",
        validators=[Optional(), Email("이메일 형식이 올바르지 않습니다."), Length(max=255)],
    )
    biz_no = StringField(
        "사업자등록번호",
        validators=[
            Optional(),
            Regexp(r"^[0-9]{3}-?[0-9]{2}-?[0-9]{5}$", message="123-45-67890 형식으로 입력하세요."),
        ],
    )
    can_clear_dtc = BooleanField("고장코드 지우기 권한")
    version = HiddenField()
