import os

import click
from flask import Flask
from flask.cli import AppGroup
from sqlalchemy import select

from app.core import audit
from app.extensions import db
from app.modules.accounts.models import User, UserType
from app.modules.accounts.passwords import hash_password


def register_cli(app: Flask) -> None:
    @app.cli.command("create-admin")
    @click.option("--tid", envvar="ADMIN_TID", required=True, help="관리자 로그인 아이디(또는 ADMIN_TID)")
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

    canlab = AppGroup("canlab", help="CAN 분석 데이터 관리")

    @canlab.command("reset")
    @click.option("--yes", is_flag=True, help="건수 확인 후 실제로 삭제한다")
    def canlab_reset(yes: bool) -> None:
        """CAN 분석 데이터를 모두 지운다. --yes 없이 실행하면 건수만 보여 준다."""
        from app.modules.canlab import service

        for table, count in service.reset_counts().items():
            click.echo(f"{table}: {count}")
        if not yes:
            click.echo("삭제하려면 --yes를 붙여 다시 실행하세요.")
            return
        service.reset_all()
        click.echo("CAN 분석 데이터를 모두 삭제했습니다.")

    app.cli.add_command(canlab)

    @app.cli.command("import-dtc-workbook")
    def import_dtc_workbook() -> None:
        """제조사별 고장코드 문서를 지식베이스에 넣는다."""
        from app.modules.knowledge.dtc_workbook import import_workbook

        stats = import_workbook()
        click.echo(
            f"문서 {stats['sheet']}건 중 저장 {stats['saved']}건, "
            f"새로 넣은 고장코드 {stats['dtcs']}건, 용어 {stats['terms']}건"
        )

    @app.cli.command("import-dtc-catalog")
    def import_dtc_catalog() -> None:
        """제조사별 DTC 설명 엑셀을 지식베이스에 초안으로 넣는다."""
        from app.modules.knowledge.dtc_catalog import import_dtc_catalog as load

        stats = load()
        click.echo(
            f"문서 {stats['sheet']}건 중 새로 넣은 고장코드 {stats['dtcs']}건, "
            f"유지 {stats['kept']}건, 저장 {stats['saved']}건"
        )

    @app.cli.command("import-wecar-app")
    def import_wecar_app() -> None:
        """위카 앱의 전기차 읽기 명령을 지식베이스에 넣는다."""
        from app.modules.knowledge.wecar_app import import_wecar_app as load

        stats = load()
        click.echo(
            f"명령 {stats['commands']}건, 수집 데이터 {stats['formulas']}건, "
            f"전기차 고장코드 {stats['dtcs']}건"
        )

    @app.cli.command("collect-knowledge")
    def collect_knowledge() -> None:
        """공개 OBD 명령·수식·고장코드 명칭을 지식베이스에 넣는다."""
        from app.modules.knowledge.collect import collect_public

        stats = collect_public()
        click.echo(
            f"명령 {stats['commands']}건, 수식 {stats['formulas']}건, "
            f"고장코드 {stats['dtcs']}건, AI 명칭 {stats['ai']}건"
        )
