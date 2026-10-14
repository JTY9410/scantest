from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileRequired
from wtforms import BooleanField, HiddenField, SelectField, SelectMultipleField, StringField, TextAreaField
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


class AnalysisForm(FlaskForm):
    trace_ids = MultiCheckboxField("기초데이터(통신 기록)", coerce=int,
                                   validators=[DataRequired("통신 기록을 하나 이상 고르세요.")])
    truth_dataset_id = SelectField("정답값 출처", coerce=int,
                                   validators=[DataRequired("정답값이 있는 데이터를 고르세요.")])
    apply = BooleanField("검증을 통과한 수식을 바로 적용", default=True)


class ReportForm(FlaskForm):
    dataset_id = SelectField("통신 기록", coerce=int, validators=[DataRequired("통신 기록을 고르세요.")])


class ActionForm(FlaskForm):
    """CSRF 토큰과 낙관적 잠금 버전만 담는 버튼용 폼."""

    version = HiddenField()
