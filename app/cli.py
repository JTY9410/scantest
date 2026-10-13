import os

import click
from flask import Flask
from sqlalchemy import select

from app.core import audit
from app.extensions import db
from app.modules.accounts.models import User, UserType
from app.modules.accounts.passwords import hash_password


def register_cli(app: Flask) -> None:
    @app.cli.command("create-admin")
    @click.option("--tid", required=True, help="관리자 로그인 아이디")
    @click.option("--name", default="관리자", show_default=True, help="표시 이름")
    def create_admin(tid: str, name: str) -> None:
        """최초 관리자를 한 번 등록한다. 비밀번호는 ADMIN_PASSWORD 또는 입력 프롬프트로 받는다."""
        if db.session.scalar(select(User).where(User.tid == tid)) is not None:
            raise click.ClickException(f"이미 존재하는 아이디입니다: {tid}")
        password = os.environ.get("ADMIN_PASSWORD") or click.prompt(
            "비밀번호", hide_input=True, confirmation_prompt=True
        )
        if len(password) < 8:
            raise click.ClickException("비밀번호는 8자 이상이어야 합니다.")
        user = User(tid=tid, name=name, type=UserType.ADMIN, password=hash_password(password))
        db.session.add(user)
        db.session.flush()
        audit.record("관리자 등록", "User", user.id, changes={"tid": tid}, message="create-admin")
        db.session.commit()
        click.echo(f"관리자 {tid} 계정을 만들었습니다. 첫 로그인 후 비밀번호를 바꾸세요.")
