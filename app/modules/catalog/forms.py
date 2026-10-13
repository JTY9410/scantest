from flask_wtf import FlaskForm
from wtforms import SelectField, StringField, TextAreaField
from wtforms.validators import DataRequired, Length, Optional, Regexp

from app.modules.scans.models import ScanType


class CompanyForm(FlaskForm):
    code = StringField(
        "기업코드",
        validators=[
            DataRequired("기업코드를 입력하세요."),
            Length(max=100),
            Regexp(r"^[A-Za-z0-9_\-]+$", message="영문, 숫자, _ - 만 사용할 수 있습니다."),
        ],
        description="앱 가입 화면에서 회원이 입력하는 코드입니다.",
    )
    name = StringField("이름", validators=[DataRequired("이름을 입력하세요."), Length(max=255)])


def _text(label: str) -> TextAreaField:
    return TextAreaField(label, validators=[Optional(), Length(max=5000)])


class CodeForm(FlaskForm):
    type = SelectField("차종", choices=[(t.value, t.label) for t in ScanType])
    code = StringField("고장코드", validators=[DataRequired("고장코드를 입력하세요."), Length(max=255)])
    unit_name = StringField("유니트명", validators=[DataRequired("유니트명을 입력하세요."), Length(max=255)])
    unit_type = StringField("유니트 구분", validators=[Optional(), Length(max=255)])
    desc = _text("설명")
    detail_desc = _text("상세 설명")
    root_cause = _text("주요 원인")
    howto_fix1 = _text("조치 방법 1")
    howto_fix2 = _text("조치 방법 2")
    howto_fix3 = _text("조치 방법 3")
