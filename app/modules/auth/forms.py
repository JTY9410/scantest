from flask_wtf import FlaskForm
from wtforms import PasswordField, StringField
from wtforms.validators import DataRequired, EqualTo, Length, Regexp

OTP = [DataRequired("OTP 코드를 입력하세요."), Regexp(r"^\s*\d{6}\s*$", message="6자리 숫자를 입력하세요.")]


class LoginForm(FlaskForm):
    tid = StringField("아이디", validators=[DataRequired("아이디를 입력하세요."), Length(max=255)])
    password = PasswordField("비밀번호", validators=[DataRequired("비밀번호를 입력하세요.")])


class OtpForm(FlaskForm):
    code = StringField("OTP 코드", validators=OTP)


class PasswordChangeForm(FlaskForm):
    current_password = PasswordField("현재 비밀번호", validators=[DataRequired("현재 비밀번호를 입력하세요.")])
    new_password = PasswordField(
        "새 비밀번호",
        validators=[
            DataRequired("새 비밀번호를 입력하세요."),
            Length(min=10, message="10자 이상 입력하세요."),
        ],
    )
    confirm_password = PasswordField(
        "새 비밀번호 확인",
        validators=[EqualTo("new_password", message="새 비밀번호와 같게 입력하세요.")],
    )
