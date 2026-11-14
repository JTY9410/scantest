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

    @app.cli.command("reset-admin-password")
    @click.option("--tid", envvar="ADMIN_TID", required=True, help="관리자 로그인 아이디(또는 ADMIN_TID)")
    def reset_admin_password(tid: str) -> None:
        """기존 관리자 비밀번호를 ADMIN_PASSWORD(또는 입력)로 맞춘다. 로컬 Docker 로그인 복구용."""
        user = db.session.scalar(select(User).where(User.tid == tid, User.deleted_at.is_(None)))
        if user is None:
            raise click.ClickException(f"관리자 아이디를 찾을 수 없습니다: {tid}")
        if user.type != UserType.ADMIN:
            raise click.ClickException(f"{tid} 는 관리자 계정이 아닙니다.")
        password = os.environ.get("ADMIN_PASSWORD") or click.prompt(
            "새 비밀번호", hide_input=True, confirmation_prompt=True
        )
        if len(password) < 8:
            raise click.ClickException("비밀번호는 8자 이상이어야 합니다.")
        user.password = hash_password(password)
        audit.record(
            "관리자 비밀번호 재설정",
            "User",
            user.id,
            user_id=user.id,
            changes={"tid": tid},
            message="reset-admin-password",
        )
        db.session.commit()
        click.echo(f"관리자 {tid} 비밀번호를 갱신했습니다. 로그인 후 필요하면 다시 바꾸세요.")

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

    @app.cli.command("import-dtc-global")
    def import_dtc_global() -> None:
        """EV·ICE 표준 고장코드 엑셀에서 없는 코드만 보강한다."""
        from app.modules.knowledge.dtc_global import import_dtc_global as load

        stats = load()
        click.echo(
            f"문서 {stats['sheet']}건 중 지식 {stats['dtcs']}건·마스터 {stats['codes']}건 추가, "
            f"제조사 표기 {stats['aliases']}건, 기존 유지 {stats['skipped']}건, 빈 설명 채움 {stats['filled']}건"
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

    definitions = AppGroup("definitions", help="차량 정의파일 관리")

    @definitions.command("import")
    @click.argument("folder_path", type=click.Path(exists=True), required=False)
    @click.option("--exclude-file", type=click.Path(exists=True), help="제외목록 JSON 파일")
    def import_definitions_cmd(folder_path: str | None, exclude_file: str | None) -> None:
        """정의파일 폴더를 DB로 import합니다.
        
        DEFINITIONS_DIR 환경변수를 설정하면 folder_path 생략 가능:
          export DEFINITIONS_DIR=/definitions
          flask definitions import
        """
        from pathlib import Path
        from app.modules.definitions.importers import import_definition_folder
        import json
        import os
        
        if not folder_path:
            folder_path = os.environ.get('DEFINITIONS_DIR')
            if not folder_path:
                click.echo("Error: folder_path required or set DEFINITIONS_DIR")
                raise click.Abort()
        
        base_path = Path(folder_path)
        if not base_path.exists():
            click.echo(f"Error: {base_path} does not exist")
            raise click.Abort()
        exclude_list = set()
        if exclude_file:
            with open(exclude_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                exclude_list = set(data.get('files', []))

        click.echo(f"Importing definitions from {base_path}")
        stats = import_definition_folder(base_path, exclude_list)

        click.echo("\nImport complete:")
        for key, value in sorted(stats.items()):
            click.echo(f"  {key}: {value}")

    @definitions.command("stats")
    def definitions_stats() -> None:
        """Import된 정의파일 통계를 표시합니다."""
        from app.modules.definitions.models import (
            DefinitionSource,
            VehicleDefinition,
            DbcMessage,
            DbcSignal,
            DiagnosticCommand,
        )

        sources = db.session.query(DefinitionSource).all()
        vehicles = db.session.query(VehicleDefinition).all()
        dbc_messages = db.session.query(DbcMessage).count()
        dbc_signals = db.session.query(DbcSignal).count()
        diag_commands = db.session.query(DiagnosticCommand).count()

        click.echo("\n=== Vehicle Definitions Statistics ===")
        click.echo(f"\nDefinition Sources: {len(sources)}")

        by_type = {}
        for src in sources:
            by_type[src.source_type] = by_type.get(src.source_type, 0) + 1

        for src_type, count in sorted(by_type.items()):
            click.echo(f"  {src_type}: {count}")

        click.echo(f"\nVehicle Mappings: {len(vehicles)}")
        click.echo(f"DBC Messages: {dbc_messages}")
        click.echo(f"DBC Signals: {dbc_signals}")
        click.echo(f"Diagnostic Commands: {diag_commands}")

        verified = db.session.query(DiagnosticCommand).filter_by(
            verification_status='verified'
        ).count()
        needs_verification = db.session.query(DiagnosticCommand).filter_by(
            verification_status='needs_verification'
        ).count()

        click.echo(f"\nDiagnostic Commands Verification:")
        click.echo(f"  Verified: {verified}")
        click.echo(f"  Needs Verification: {needs_verification}")
    
    @definitions.command("classify")
    def definitions_classify() -> None:
        """전체 정의 데이터를 재분류합니다 (ECU, powertrain, signal_category)."""
        from app.modules.definitions.classifier import reclassify_all_definitions
        
        summary = reclassify_all_definitions()
        
        click.echo("\n=== Classification Summary ===")
        for table_col, counts in summary.items():
            click.echo(f"\n{table_col}:")
            for key, count in counts.items():
                click.echo(f"  {key}: {count}")

    app.cli.add_command(definitions)
    
    # Database audit command
    @app.cli.command("audit")
    @click.argument("scope", default="db")
    def audit_db(scope: str) -> None:
        """Run database integrity audit. Usage: flask audit db"""
        if scope != "db":
            click.echo(f"Unknown audit scope: {scope}")
            return
        
        from sqlalchemy import text
        
        click.echo("=" * 80)
        click.echo("DATABASE INTEGRITY AUDIT")
        click.echo("=" * 80)
        click.echo()
        
        results = {}
        failed_count = 0
        
        # 1. Orphans & FK Integrity
        click.echo("\nOrphans & Foreign Key Integrity")
        click.echo("-" * 80)
        
        orphan_scans = db.session.execute(text("""
            SELECT COUNT(*) FROM scans 
            WHERE tester_id IS NOT NULL 
            AND NOT EXISTS (SELECT 1 FROM users WHERE id = scans.tester_id)
        """)).scalar()
        status = "✓" if orphan_scans == 0 else "✗"
        color = "green" if orphan_scans == 0 else "red"
        click.echo(click.style(f"  {status} Orphaned scans (no tester): {orphan_scans}", fg=color))
        if orphan_scans > 0: failed_count += 1
        
        # 2. Duplicates
        click.echo("\nDuplicates")
        click.echo("-" * 80)
        
        dup_specs = db.session.execute(text("""
            SELECT COUNT(*) FROM (
                SELECT maker, model, trim_grade, model_year, COUNT(*) as cnt
                FROM battery_specs
                WHERE is_active = true
                GROUP BY maker, model, trim_grade, model_year
                HAVING COUNT(*) > 1
            ) sub
        """)).scalar()
        status = "✓" if dup_specs == 0 else "✗"
        color = "green" if dup_specs == 0 else "red"
        click.echo(click.style(f"  {status} Duplicate battery specs: {dup_specs} groups", fg=color))
        if dup_specs > 0: failed_count += 1
        
        # 3. Values Without Source
        click.echo("\nValues Without Source")
        click.echo("-" * 80)
        
        no_source_specs = db.session.execute(text("""
            SELECT COUNT(*) FROM battery_specs
            WHERE is_active = true
            AND (source_url IS NULL OR source_url = '')
        """)).scalar()
        status = "✓" if no_source_specs == 0 else "✗"
        color = "green" if no_source_specs == 0 else "red"
        click.echo(click.style(f"  {status} Battery specs without source_url: {no_source_specs}", fg=color))
        if no_source_specs > 0: failed_count += 1
        
        no_citation_rules = db.session.execute(text("""
            SELECT COUNT(*) FROM vin_decode_rules
            WHERE citation_url IS NULL OR citation_url = ''
        """)).scalar()
        status = "✓" if no_citation_rules == 0 else "✗"
        color = "green" if no_citation_rules == 0 else "red"
        click.echo(click.style(f"  {status} VIN rules without citation: {no_citation_rules}", fg=color))
        if no_citation_rules > 0: failed_count += 1
        
        # 4. Unclassified Counts by Maker  
        click.echo("\nUnclassified Counts by Maker")
        click.echo("-" * 80)
        
        # Get powertrain breakdown
        powertrain_counts = db.session.execute(text("""
            SELECT powertrain, COUNT(*) as count
            FROM vehicle_definitions
            GROUP BY powertrain
            ORDER BY count DESC
        """)).fetchall()
        
        click.echo("  Powertrain distribution:")
        for row in powertrain_counts:
            pt = row[0] or 'NULL'
            click.echo(f"    {pt}: {row[1]}")
        
        # Get unclassified (unknown) by maker
        unclassified = db.session.execute(text("""
            SELECT maker, COUNT(*) as count
            FROM vehicle_definitions
            WHERE powertrain = 'unknown'
            AND maker IS NOT NULL
            GROUP BY maker
            ORDER BY count DESC
        """)).fetchall()
        
        total_unknown = sum(row[1] for row in unclassified)
        click.echo(f"\n  Unknown by maker (total {total_unknown}):")
        for row in unclassified:
            click.echo(f"    • {row[0]}: {row[1]}")
        
        # Get not_vehicle separately
        not_vehicle = db.session.execute(text("""
            SELECT COUNT(*) FROM vehicle_definitions
            WHERE powertrain = 'not_vehicle'
        """)).scalar()
        click.echo(f"\n  Not vehicle: {not_vehicle}")
        
        # 5. Conflicts & Overrides
        click.echo("\nConflicts & Overrides")
        click.echo("-" * 80)
        
        conflict_scans = db.session.execute(text("""
            SELECT COUNT(*) FROM scans
            WHERE powertrain_conflict = true
            AND deleted_at IS NULL
        """)).scalar()
        click.echo(click.style(f"  ✓ Scans with powertrain conflicts: {conflict_scans}", fg="green"))
        
        override_count = db.session.execute(text("""
            SELECT COUNT(DISTINCT COALESCE(scan_id, vehicle_definition_id))
            FROM powertrain_override_audit
        """)).scalar()
        click.echo(click.style(f"  ✓ Records with manual overrides: {override_count}", fg="green"))
        
        # 6. UNKNOWN Ratios
        click.echo("\nUNKNOWN Ratios")
        click.echo("-" * 80)
        
        # Commands with UNKNOWN/NULL ecu_module
        unknown_cmd_ecu = db.session.execute(text("""
            SELECT COUNT(*) FROM diagnostic_commands
            WHERE ecu_module IS NULL OR UPPER(ecu_module) = 'UNKNOWN'
        """)).scalar()
        
        # Commands with unknown protocol
        unknown_cmd_protocol = db.session.execute(text("""
            SELECT COUNT(*) FROM diagnostic_commands
            WHERE protocol IS NULL OR LOWER(protocol) = 'unknown'
        """)).scalar()
        
        total_cmds = db.session.execute(text("SELECT COUNT(*) FROM diagnostic_commands")).scalar()
        ecu_ratio = (unknown_cmd_ecu / total_cmds * 100) if total_cmds > 0 else 0
        protocol_ratio = (unknown_cmd_protocol / total_cmds * 100) if total_cmds > 0 else 0
        
        ecu_fail = ecu_ratio >= 10
        protocol_fail = protocol_ratio >= 10
        
        status = "✓" if not ecu_fail else "✗"
        color = "green" if not ecu_fail else "red"
        click.echo(click.style(f"  {status} Commands ecu_module UNKNOWN/NULL: {unknown_cmd_ecu}/{total_cmds} ({ecu_ratio:.1f}%)", fg=color))
        if ecu_fail: failed_count += 1
        
        status = "✓" if not protocol_fail else "✗"
        color = "green" if not protocol_fail else "red"
        click.echo(click.style(f"  {status} Commands protocol unknown/NULL: {unknown_cmd_protocol}/{total_cmds} ({protocol_ratio:.1f}%)", fg=color))
        if protocol_fail: failed_count += 1
        
        # DBC signals with UNKNOWN/NULL ecu_module
        unknown_sig_ecu = db.session.execute(text("""
            SELECT COUNT(*) FROM dbc_signals
            WHERE ecu_module IS NULL OR UPPER(ecu_module) = 'UNKNOWN'
        """)).scalar()
        
        # DBC signals with other/UNKNOWN/NULL signal_category
        unknown_sig_cat = db.session.execute(text("""
            SELECT COUNT(*) FROM dbc_signals
            WHERE signal_category IS NULL 
            OR UPPER(signal_category) IN ('UNKNOWN', 'OTHER')
        """)).scalar()
        
        total_signals = db.session.execute(text("SELECT COUNT(*) FROM dbc_signals")).scalar()
        sig_ecu_ratio = (unknown_sig_ecu / total_signals * 100) if total_signals > 0 else 0
        sig_cat_ratio = (unknown_sig_cat / total_signals * 100) if total_signals > 0 else 0
        
        sig_ecu_fail = sig_ecu_ratio >= 10
        sig_cat_fail = sig_cat_ratio >= 10
        
        status = "✓" if not sig_ecu_fail else "✗"
        color = "green" if not sig_ecu_fail else "red"
        click.echo(click.style(f"  {status} DBC signals ecu_module UNKNOWN/NULL: {unknown_sig_ecu}/{total_signals} ({sig_ecu_ratio:.1f}%)", fg=color))
        if sig_ecu_fail: failed_count += 1
        
        status = "✓" if not sig_cat_fail else "✗"
        color = "green" if not sig_cat_fail else "red"
        click.echo(click.style(f"  {status} DBC signals signal_category other/UNKNOWN/NULL: {unknown_sig_cat}/{total_signals} ({sig_cat_ratio:.1f}%)", fg=color))
        if sig_cat_fail: failed_count += 1
        
        # Summary
        click.echo()
        click.echo("=" * 80)
        if failed_count > 0:
            click.echo(click.style(f"SUMMARY: {failed_count} checks failed", fg="red", bold=True))
        else:
            click.echo(click.style("SUMMARY: All checks passed!", fg="green", bold=True))
        click.echo("=" * 80)
    
    # Battery management commands
    from app.modules.battery.cli import battery
    app.cli.add_command(battery)
