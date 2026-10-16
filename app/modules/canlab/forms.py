from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileRequired, MultipleFileField
from wtforms import HiddenField, SelectField, StringField, TextAreaField
from wtforms.validators import DataRequired, Length, Optional

from app.modules.canlab.models import DatasetKind


class UploadForm(FlaskForm):
    file = FileField("파일", validators=[FileRequired("올릴 파일을 고르세요.")])
    kind = SelectField("데이터 종류", choices=[(k.value, k.label) for k in DatasetKind])
    vehicle = StringField("차량", validators=[DataRequired("차량 이름을 입력하세요."), Length(max=100)])
    note = StringField("메모", validators=[Optional(), Length(max=500)])


class TruthTextForm(FlaskForm):
    text = TextAreaField("정답값 직접 입력", validators=[DataRequired("입력할 값을 붙여 넣으세요.")])


class InputForm(FlaskForm):
    car_no = StringField("차량번호", validators=[DataRequired("차량번호를 입력하세요."), Length(max=20)])
    wescan_file = FileField("위스캔 통신기록", validators=[FileRequired("위스캔 통신기록 파일을 고르세요.")])
    values_file = FileField("위스캔 최종값 파일")
    values_text = TextAreaField("위스캔 최종값 붙여넣기", validators=[Optional()])
    reverse_files = MultipleFileField("리버스데이터")


class CompareForm(FlaskForm):
    dataset_id = SelectField("저장된 스캔 통신기록", coerce=lambda v: int(v) if v else 0,
                             validators=[Optional()])
    scan_file = FileField("스캔 통신기록 파일")
    values_file = FileField("위스캔 결과치 파일")
    values_text = TextAreaField("위스캔 결과치 붙여넣기", validators=[Optional()])


class ReferenceUrlForm(FlaskForm):
    url = StringField("자료 주소", validators=[DataRequired("자료 주소를 입력하세요."), Length(max=500)])
    title = StringField("제목", validators=[Optional(), Length(max=200)])
    maker = StringField("제조사", validators=[Optional(), Length(max=50)])
    model = StringField("모델", validators=[Optional(), Length(max=100)])


class ObdbSyncForm(FlaskForm):
    repo = StringField("추가 저장소", validators=[Optional(), Length(max=80)])
    keywords = StringField("모델 키워드", validators=[Optional(), Length(max=200)])


class ReportForm(FlaskForm):
    dataset_id = SelectField("통신 기록", coerce=int, validators=[DataRequired("통신 기록을 고르세요.")])


class ActionForm(FlaskForm):
    """CSRF 토큰과 낙관적 잠금 버전만 담는 버튼용 폼."""

    version = HiddenField()
