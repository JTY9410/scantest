from flask_wtf import FlaskForm
from wtforms import (
    DecimalField,
    HiddenField,
    IntegerField,
    PasswordField,
    SelectMultipleField,
    StringField,
)
from wtforms.validators import DataRequired, Length, NumberRange, Optional, Regexp
from wtforms.widgets import CheckboxInput, ListWidget

from app.modules.admin.models import AI_FEATURES


class CheckboxListField(SelectMultipleField):
    widget = ListWidget(prefix_label=False)
    option_widget = CheckboxInput()


class AiSettingsForm(FlaskForm):
    model = StringField(
        "모델",
        validators=[
            DataRequired("모델 이름을 입력하세요."),
            Length(max=100),
            Regexp(r"^[A-Za-z0-9._:\-/]+$", message="영문, 숫자, . _ : - / 만 사용할 수 있습니다."),
        ],
    )
    features = CheckboxListField("사용할 기능", choices=list(AI_FEATURES.items()))
    monthly_budget = DecimalField(
        "월 예산 상한(USD)",
        places=2,
        validators=[Optional(), NumberRange(min=0, message="0 이상 입력하세요.")],
    )
    monthly_token_limit = IntegerField(
        "월 토큰 상한",
        validators=[Optional(), NumberRange(min=0, message="0 이상 입력하세요.")],
    )
    version = HiddenField()


class AiKeyForm(FlaskForm):
    api_key = PasswordField("API 키", validators=[DataRequired("API 키를 입력하세요."), Length(min=8, max=500)])


class CarInfoUrlForm(FlaskForm):
    url = StringField("조회 주소", validators=[DataRequired("주소를 입력하세요."), Length(max=500)])
    version = HiddenField()


class CarInfoKeyForm(FlaskForm):
    api_key = PasswordField("인증키", validators=[DataRequired("인증키를 입력하세요."), Length(min=4, max=500)])


class CarInfoTestForm(FlaskForm):
    car_no = StringField("차량번호", validators=[DataRequired("차량번호를 입력하세요."), Length(max=20)])
