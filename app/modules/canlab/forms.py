from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileRequired
from wtforms import HiddenField, SelectField, SelectMultipleField, StringField, TextAreaField
from wtforms.validators import DataRequired, Length, Optional
from wtforms.widgets import CheckboxInput, ListWidget

from app.modules.canlab.models import DatasetKind


class UploadForm(FlaskForm):
    file = FileField("파일", validators=[FileRequired("올릴 파일을 고르세요.")])
    kind = SelectField("데이터 종류", choices=[(k.value, k.label) for k in DatasetKind])
    vehicle = StringField("차량", validators=[DataRequired("차량 이름을 입력하세요."), Length(max=100)])
    note = StringField("메모", validators=[Optional(), Length(max=500)])


class TruthTextForm(FlaskForm):
    text = TextAreaField("정답값 직접 입력", validators=[DataRequired("입력할 값을 붙여 넣으세요.")])


class MultiCheckboxField(SelectMultipleField):
    widget = ListWidget(prefix_label=False)
    option_widget = CheckboxInput()


class WescanForm(FlaskForm):
    file = FileField("위스캔 통신 기록", validators=[FileRequired("위스캔 통신 기록 파일을 고르세요.")])
    values_file = FileField("위스캔 최종값 파일")
    values_text = TextAreaField("위스캔 최종값 붙여넣기", validators=[Optional()])
    vehicle = StringField("차량", validators=[DataRequired("차량 이름을 입력하세요."), Length(max=100)])
    note = StringField("메모", validators=[Optional(), Length(max=500)])


class ReverseForm(FlaskForm):
    file = FileField("리버스 데이터(TRC)", validators=[FileRequired("리버스 데이터 파일을 고르세요.")])
    vehicle = StringField("차량", validators=[DataRequired("차량 이름을 입력하세요."), Length(max=100)])
    note = StringField("메모", validators=[Optional(), Length(max=500)])


class AnalysisForm(FlaskForm):
    wescan_id = SelectField("위스캔 데이터(최종값)", coerce=int,
                            validators=[DataRequired("최종값이 있는 위스캔 데이터를 고르세요.")])
    reverse_ids = MultiCheckboxField("리버스 데이터", coerce=int,
                                     validators=[DataRequired("리버스 데이터를 하나 이상 고르세요.")])


class ReportForm(FlaskForm):
    dataset_id = SelectField("통신 기록", coerce=int, validators=[DataRequired("통신 기록을 고르세요.")])


class ActionForm(FlaskForm):
    """CSRF 토큰과 낙관적 잠금 버전만 담는 버튼용 폼."""

    version = HiddenField()
