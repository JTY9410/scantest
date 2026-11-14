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
    
    @definitions.command("normalize-makers")
    @click.option("--report-only", is_flag=True, help="Show before/after stats without applying changes")
    @click.option("--yes", is_flag=True, help="Apply normalization without confirmation")
    def normalize_makers(report_only: bool, yes: bool) -> None:
        """Normalize maker names and mark test/generic entries as not_vehicle.
        
        Usage:
            flask definitions normalize-makers --report-only  # Show before stats only
            flask definitions normalize-makers --yes          # Apply normalization
        """
        from sqlalchemy import text
        from app.core.makers import normalize_maker, is_not_vehicle_maker, extract_model_from_maker_field, derive_maker_from_path
        
        click.echo("=" * 80)
        click.echo("MAKER NORMALIZATION")
        click.echo("=" * 80)
        click.echo()
        
        # BEFORE stats
        click.echo("BEFORE Normalization:")
        click.echo("-" * 80)
        
        distinct_makers_before = db.session.execute(text("""
            SELECT COUNT(DISTINCT maker) FROM vehicle_definitions WHERE maker IS NOT NULL
        """)).scalar()
        null_makers_before = db.session.execute(text("""
            SELECT COUNT(*) FROM vehicle_definitions WHERE maker IS NULL
        """)).scalar()
        click.echo(f"  Distinct makers: {distinct_makers_before}")
        click.echo(f"  NULL makers: {null_makers_before}")
        
        powertrain_before = db.session.execute(text("""
            SELECT powertrain, COUNT(*) as count
            FROM vehicle_definitions
            GROUP BY powertrain
            ORDER BY count DESC
        """)).fetchall()
        
        click.echo("\n  Powertrain distribution:")
        for row in powertrain_before:
            pt = row[0] or 'NULL'
            click.echo(f"    {pt}: {row[1]}")
        
        if report_only:
            click.echo("\n(Use --yes to apply normalization)")
            return
        
        if not yes:
            click.echo("\nThis will:")
            click.echo("  1. Normalize maker spelling variants")
            click.echo("  2. Split 'Maker_ Model' patterns and populate model column")
            click.echo("  3. Mark test/generic entries as not_vehicle")
            click.echo("  4. Derive maker from file paths for NULL makers")
            click.echo("  5. Reclassify powertrains")
            
            if not click.confirm("\nProceed with normalization?"):
                click.echo("Aborted.")
                return
        
        click.echo("\nApplying normalization...")
        click.echo("-" * 80)
        
        # Step 1: Mark not_vehicle entries FIRST
        click.echo("  1. Marking test/generic entries as not_vehicle...")
        
        not_vehicle_makers = [
            'comma', '_테스트_예제', '_공통_센서', '공용규격', '공통규격'
        ]
        
        marked_not_vehicle = 0
        for maker in not_vehicle_makers:
            result = db.session.execute(text("""
                UPDATE vehicle_definitions
                SET powertrain = 'not_vehicle'
                WHERE maker = :maker AND powertrain != 'not_vehicle'
            """), {'maker': maker})
            marked_not_vehicle += result.rowcount
        
        # AAA_ prefix
        result = db.session.execute(text("""
            UPDATE vehicle_definitions
            SET powertrain = 'not_vehicle'
            WHERE maker LIKE 'AAA\\_%' AND powertrain != 'not_vehicle'
        """))
        marked_not_vehicle += result.rowcount
        
        # _공통 prefix
        result = db.session.execute(text("""
            UPDATE vehicle_definitions
            SET powertrain = 'not_vehicle'
            WHERE maker LIKE '_공통%' AND powertrain != 'not_vehicle'
        """))
        marked_not_vehicle += result.rowcount
        
        db.session.commit()
        click.echo(f"     → Marked {marked_not_vehicle} rows as not_vehicle")
        
        # Step 2: Split 'Maker_ Model' patterns and populate model column
        click.echo("  2. Splitting 'Maker_ Model' patterns...")
        
        vehicles_to_split = db.session.execute(text("""
            SELECT id, maker, model FROM vehicle_definitions
            WHERE powertrain != 'not_vehicle' 
            AND maker IS NOT NULL
            AND (maker LIKE '%\\_%' OR maker LIKE '% %')
        """)).fetchall()
        
        split_count = 0
        for vehicle_id, maker_value, current_model in vehicles_to_split:
            extracted_maker, extracted_model = extract_model_from_maker_field(maker_value)
            
            if extracted_maker and extracted_model and not current_model:
                # Split succeeded and model is empty - populate it
                db.session.execute(text("""
                    UPDATE vehicle_definitions
                    SET maker = :maker, model = :model
                    WHERE id = :id
                """), {'id': vehicle_id, 'maker': extracted_maker, 'model': extracted_model})
                split_count += 1
            elif extracted_maker and extracted_maker != maker_value:
                # Just normalize the maker without splitting
                db.session.execute(text("""
                    UPDATE vehicle_definitions
                    SET maker = :maker
                    WHERE id = :id
                """), {'id': vehicle_id, 'maker': extracted_maker})
                split_count += 1
        
        db.session.commit()
        click.echo(f"     → Split/normalized {split_count} rows")
        
        # Step 3: Python-based normalization for remaining rows
        click.echo("  3. Normalizing remaining makers...")
        
        vehicles = db.session.execute(text("""
            SELECT id, maker FROM vehicle_definitions
            WHERE powertrain != 'not_vehicle' 
            AND maker IS NOT NULL
            AND maker NOT LIKE '%\\_%'
            AND maker NOT LIKE '% %'
        """)).fetchall()
        
        normalized_count = 0
        for vehicle_id, maker in vehicles:
            normalized = normalize_maker(maker)
            
            if normalized is None:
                db.session.execute(text("""
                    UPDATE vehicle_definitions
                    SET powertrain = 'not_vehicle'
                    WHERE id = :id
                """), {'id': vehicle_id})
                normalized_count += 1
            elif normalized != maker:
                db.session.execute(text("""
                    UPDATE vehicle_definitions
                    SET maker = :normalized
                    WHERE id = :id
                """), {'id': vehicle_id, 'normalized': normalized})
                normalized_count += 1
        
        db.session.commit()
        click.echo(f"     → Normalized {normalized_count} rows")
        
        # Step 4: Derive maker from path for NULL makers
        click.echo("  4. Deriving makers from file paths for NULL entries...")
        
        null_makers = db.session.execute(text("""
            SELECT vd.id, ds.file_path, vd.model
            FROM vehicle_definitions vd
            LEFT JOIN definition_sources ds ON vd.source_id = ds.id
            WHERE vd.maker IS NULL AND vd.powertrain != 'not_vehicle'
        """)).fetchall()
        
        derived_count = 0
        for vehicle_id, file_path, model in null_makers:
            derived_maker = derive_maker_from_path(file_path, model)
            
            if derived_maker:
                db.session.execute(text("""
                    UPDATE vehicle_definitions
                    SET maker = :maker
                    WHERE id = :id
                """), {'id': vehicle_id, 'maker': derived_maker})
                derived_count += 1
        
        db.session.commit()
        click.echo(f"     → Derived {derived_count} makers from paths")
        
        # Step 5: Rerun classification
        click.echo("  5. Re-running powertrain classification...")
        from app.modules.definitions.vehicle_classifier import classify_vehicle_powertrain
        
        vehicles_to_classify = db.session.execute(text("""
            SELECT vd.id, vd.maker, vd.model, vd.submodel, ds.file_path
            FROM vehicle_definitions vd
            LEFT JOIN definition_sources ds ON vd.source_id = ds.id
            WHERE vd.powertrain != 'not_vehicle'
        """)).fetchall()
        
        classified = 0
        for veh_id, maker, model, submodel, file_path in vehicles_to_classify:
            powertrain, source, confidence, conflict = classify_vehicle_powertrain(
                maker=maker,
                model=model,
                submodel=submodel,
                file_path=file_path
            )
            
            db.session.execute(text("""
                UPDATE vehicle_definitions
                SET powertrain = :powertrain
                WHERE id = :id
            """), {'id': veh_id, 'powertrain': powertrain})
            classified += 1
        
        db.session.commit()
        click.echo(f"     → Classified {classified} rows")
        
        # AFTER stats
        click.echo()
        click.echo("AFTER Normalization:")
        click.echo("-" * 80)
        
        distinct_makers_after = db.session.execute(text("""
            SELECT COUNT(DISTINCT maker) FROM vehicle_definitions WHERE maker IS NOT NULL
        """)).scalar()
        null_makers_after = db.session.execute(text("""
            SELECT COUNT(*) FROM vehicle_definitions WHERE maker IS NULL
        """)).scalar()
        click.echo(f"  Distinct makers: {distinct_makers_after}")
        click.echo(f"  NULL makers: {null_makers_after}")
        
        powertrain_after = db.session.execute(text("""
            SELECT powertrain, COUNT(*) as count
            FROM vehicle_definitions
            GROUP BY powertrain
            ORDER BY count DESC
        """)).fetchall()
        
        click.echo("\n  Powertrain distribution:")
        for row in powertrain_after:
            pt = row[0] or 'NULL'
            click.echo(f"    {pt}: {row[1]}")
        
        # List ALL distinct makers
        click.echo("\n  All distinct makers:")
        all_makers = db.session.execute(text("""
            SELECT DISTINCT maker FROM vehicle_definitions
            WHERE maker IS NOT NULL
            ORDER BY maker
        """)).fetchall()
        
        for row in all_makers:
            click.echo(f"    • {row[0]}")
        
        # Summary
        click.echo()
        click.echo("=" * 80)
        maker_reduction = distinct_makers_before - distinct_makers_after
        null_reduction = null_makers_before - null_makers_after
        click.echo(f"SUMMARY: Makers {distinct_makers_before} → {distinct_makers_after} (-{maker_reduction}), NULL {null_makers_before} → {null_makers_after} (-{null_reduction})")
        click.echo("=" * 80)
    
    @definitions.command("recover-destroyed-makers")
    @click.option("--yes", is_flag=True, help="Apply recovery without confirmation")
    def recover_destroyed_makers(yes: bool) -> None:
        """Recover maker names that were incorrectly truncated during normalization.
        
        Recovers:
        - 'Aston' → 'Aston Martin'
        - 'MV' → 'MV Agusta'
        - 'Legend' → 'Legend Cars'
        - 'SCCA' → 'SCCA Enterprises'
        - 'BT1' → 'General Motors'
        Also fixes '공통규격' to not_vehicle.
        """
        from sqlalchemy import text
        
        click.echo("=" * 80)
        click.echo("RECOVER DESTROYED MAKER NAMES")
        click.echo("=" * 80)
        click.echo()
        
        # Show current counts
        click.echo("Current truncated maker counts:")
        for maker in ['Aston', 'MV', 'Legend', 'SCCA', 'BT1', '공통규격']:
            count = db.session.execute(text("""
                SELECT COUNT(*) FROM vehicle_definitions WHERE maker = :maker
            """), {'maker': maker}).scalar()
            if count > 0:
                click.echo(f"  {maker}: {count} rows")
        
        if not yes:
            if not click.confirm("\nRecover these makers from file paths?"):
                click.echo("Aborted.")
                return
        
        click.echo("\nRecovering makers...")
        
        # 1. Aston -> Aston Martin
        result = db.session.execute(text("""
            UPDATE vehicle_definitions vd
            SET maker = 'Aston Martin'
            FROM definition_sources ds
            WHERE vd.source_id = ds.id
            AND vd.maker = 'Aston'
            AND (ds.file_path ILIKE '%Aston%Martin%' OR ds.file_path ILIKE '%AstonMartin%')
        """))
        click.echo(f"  Aston → Aston Martin: {result.rowcount} rows")
        
        # 2. MV -> MV Agusta
        result = db.session.execute(text("""
            UPDATE vehicle_definitions vd
            SET maker = 'MV Agusta'
            FROM definition_sources ds
            WHERE vd.source_id = ds.id
            AND vd.maker = 'MV'
            AND (ds.file_path ILIKE '%MV%Agusta%' OR ds.file_path ILIKE '%MVAgusta%')
        """))
        click.echo(f"  MV → MV Agusta: {result.rowcount} rows")
        
        # 3. Legend -> Legend Cars
        result = db.session.execute(text("""
            UPDATE vehicle_definitions vd
            SET maker = 'Legend Cars'
            FROM definition_sources ds
            WHERE vd.source_id = ds.id
            AND vd.maker = 'Legend'
            AND (ds.file_path ILIKE '%Legend%Cars%' OR ds.file_path ILIKE '%LegendCars%')
        """))
        click.echo(f"  Legend → Legend Cars: {result.rowcount} rows")
        
        # 4. SCCA -> SCCA Enterprises
        result = db.session.execute(text("""
            UPDATE vehicle_definitions vd
            SET maker = 'SCCA Enterprises'
            FROM definition_sources ds
            WHERE vd.source_id = ds.id
            AND vd.maker = 'SCCA'
            AND (ds.file_path ILIKE '%SCCA%Enterprises%' OR ds.file_path ILIKE '%SCCAEnterprises%')
        """))
        click.echo(f"  SCCA → SCCA Enterprises: {result.rowcount} rows")
        
        # 5. BT1 -> General Motors
        result = db.session.execute(text("""
            UPDATE vehicle_definitions vd
            SET maker = 'General Motors'
            FROM definition_sources ds
            WHERE vd.source_id = ds.id
            AND vd.maker = 'BT1'
            AND ds.file_path ILIKE '%BT1%'
        """))
        click.echo(f"  BT1 → General Motors: {result.rowcount} rows")
        
        # 6. 공통규격 -> not_vehicle
        result = db.session.execute(text("""
            UPDATE vehicle_definitions
            SET powertrain = 'not_vehicle'
            WHERE maker = '공통규격' AND powertrain != 'not_vehicle'
        """))
        click.echo(f"  공통규격 → not_vehicle: {result.rowcount} rows")
        
        db.session.commit()
        
        click.echo()
        click.echo("=" * 80)
        click.echo("Recovery complete.")
        click.echo("=" * 80)

    @definitions.command("backfill-ecu")
    @click.option("--report-only", is_flag=True, help="Show before/after stats without applying changes")
    @click.option("--yes", is_flag=True, help="Apply backfill without confirmation")
    def backfill_ecu(report_only: bool, yes: bool) -> None:
        """Backfill ECU module and signal category from explicit source file evidence.
        
        Phase 6: Evidence-based classification only - no guessing or inference.
        
        Usage:
            flask definitions backfill-ecu --report-only  # Show before stats only
            flask definitions backfill-ecu --yes          # Apply backfill
        """
        from sqlalchemy import text
        from app.modules.definitions.ecu_backfill import extract_ecu_from_evidence, extract_category_from_evidence
        
        click.echo("=" * 80)
        click.echo("ECU/CATEGORY BACKFILL (Evidence-Based Only)")
        click.echo("=" * 80)
        click.echo()
        
        # BEFORE stats
        click.echo("BEFORE Backfill:")
        click.echo("-" * 80)
        
        # Commands ECU stats
        cmd_total = db.session.execute(text("""
            SELECT COUNT(*) FROM diagnostic_commands
        """)).scalar()
        
        cmd_unknown = db.session.execute(text("""
            SELECT COUNT(*) FROM diagnostic_commands
            WHERE ecu_module IS NULL OR ecu_module = 'UNKNOWN'
        """)).scalar()
        
        cmd_unknown_pct = (cmd_unknown / cmd_total * 100) if cmd_total > 0 else 0
        click.echo(f"  Commands ECU UNKNOWN/NULL: {cmd_unknown:,} / {cmd_total:,} ({cmd_unknown_pct:.1f}%)")
        
        # DBC signals ECU stats
        sig_total = db.session.execute(text("""
            SELECT COUNT(*) FROM dbc_signals
        """)).scalar()
        
        sig_ecu_unknown = db.session.execute(text("""
            SELECT COUNT(*) FROM dbc_signals
            WHERE ecu_module IS NULL OR ecu_module = 'UNKNOWN'
        """)).scalar()
        
        sig_ecu_unknown_pct = (sig_ecu_unknown / sig_total * 100) if sig_total > 0 else 0
        click.echo(f"  DBC signals ECU UNKNOWN/NULL: {sig_ecu_unknown:,} / {sig_total:,} ({sig_ecu_unknown_pct:.1f}%)")
        
        # DBC signals category stats
        sig_cat_unknown = db.session.execute(text("""
            SELECT COUNT(*) FROM dbc_signals
            WHERE signal_category IS NULL OR signal_category IN ('UNKNOWN', 'other')
        """)).scalar()
        
        sig_cat_unknown_pct = (sig_cat_unknown / sig_total * 100) if sig_total > 0 else 0
        click.echo(f"  DBC signals category UNKNOWN/other/NULL: {sig_cat_unknown:,} / {sig_total:,} ({sig_cat_unknown_pct:.1f}%)")
        
        if report_only:
            click.echo("\n(Use --yes to apply backfill)")
            return
        
        if not yes:
            click.echo("\nThis will:")
            click.echo("  1. Extract ECU modules from file paths, command labels, and signal names")
            click.echo("  2. Extract signal categories from signal names and descriptions")
            click.echo("  3. Update only where explicit evidence exists (no guessing)")
            
            if not click.confirm("\nProceed with backfill?"):
                click.echo("Aborted.")
                return
        
        click.echo("\nApplying backfill...")
        click.echo("-" * 80)
        
        # Step 1: Backfill diagnostic_commands ECU
        click.echo("  1. Backfilling diagnostic_commands ECU module...")
        
        commands = db.session.execute(text("""
            SELECT dc.id, dc.label, ds.file_path
            FROM diagnostic_commands dc
            LEFT JOIN definition_sources ds ON dc.source_id = ds.id
            WHERE dc.ecu_module IS NULL OR dc.ecu_module = 'UNKNOWN'
        """)).fetchall()
        
        cmd_updated = 0
        for cmd_id, label, file_path in commands:
            ecu = extract_ecu_from_evidence(
                file_path=file_path,
                command_label=label
            )
            
            if ecu:
                db.session.execute(text("""
                    UPDATE diagnostic_commands
                    SET ecu_module = :ecu
                    WHERE id = :id
                """), {'id': cmd_id, 'ecu': ecu})
                cmd_updated += 1
        
        db.session.commit()
        click.echo(f"     → Updated {cmd_updated} commands")
        
        # Step 2: Backfill dbc_signals ECU
        click.echo("  2. Backfilling dbc_signals ECU module...")
        
        signals = db.session.execute(text("""
            SELECT ds.id, ds.signal_name, ds.sender_ecu, ds.comment, src.file_path
            FROM dbc_signals ds
            LEFT JOIN definition_sources src ON ds.source_id = src.id
            WHERE ds.ecu_module IS NULL OR ds.ecu_module = 'UNKNOWN'
        """)).fetchall()
        
        sig_ecu_updated = 0
        for sig_id, signal_name, sender_ecu, comment, file_path in signals:
            ecu = extract_ecu_from_evidence(
                file_path=file_path,
                signal_name=signal_name,
                dbc_comment=comment
            )
            
            # Also check sender_ecu field if available
            if not ecu and sender_ecu:
                ecu = extract_ecu_from_evidence(command_label=sender_ecu)
            
            if ecu:
                db.session.execute(text("""
                    UPDATE dbc_signals
                    SET ecu_module = :ecu
                    WHERE id = :id
                """), {'id': sig_id, 'ecu': ecu})
                sig_ecu_updated += 1
        
        db.session.commit()
        click.echo(f"     → Updated {sig_ecu_updated} signals")
        
        # Step 3: Backfill dbc_signals category
        click.echo("  3. Backfilling dbc_signals category...")
        
        signals_cat = db.session.execute(text("""
            SELECT ds.id, ds.signal_name, ds.comment
            FROM dbc_signals ds
            WHERE ds.signal_category IS NULL OR ds.signal_category IN ('UNKNOWN', 'other')
        """)).fetchall()
        
        sig_cat_updated = 0
        for sig_id, signal_name, comment in signals_cat:
            category = extract_category_from_evidence(
                signal_name=signal_name,
                dbc_comment=comment
            )
            
            if category:
                db.session.execute(text("""
                    UPDATE dbc_signals
                    SET signal_category = :category
                    WHERE id = :id
                """), {'id': sig_id, 'category': category})
                sig_cat_updated += 1
        
        db.session.commit()
        click.echo(f"     → Updated {sig_cat_updated} signals")
        
        # AFTER stats
        click.echo()
        click.echo("AFTER Backfill:")
        click.echo("-" * 80)
        
        cmd_unknown_after = db.session.execute(text("""
            SELECT COUNT(*) FROM diagnostic_commands
            WHERE ecu_module IS NULL OR ecu_module = 'UNKNOWN'
        """)).scalar()
        
        cmd_unknown_pct_after = (cmd_unknown_after / cmd_total * 100) if cmd_total > 0 else 0
        click.echo(f"  Commands ECU UNKNOWN/NULL: {cmd_unknown_after:,} / {cmd_total:,} ({cmd_unknown_pct_after:.1f}%)")
        
        sig_ecu_unknown_after = db.session.execute(text("""
            SELECT COUNT(*) FROM dbc_signals
            WHERE ecu_module IS NULL OR ecu_module = 'UNKNOWN'
        """)).scalar()
        
        sig_ecu_unknown_pct_after = (sig_ecu_unknown_after / sig_total * 100) if sig_total > 0 else 0
        click.echo(f"  DBC signals ECU UNKNOWN/NULL: {sig_ecu_unknown_after:,} / {sig_total:,} ({sig_ecu_unknown_pct_after:.1f}%)")
        
        sig_cat_unknown_after = db.session.execute(text("""
            SELECT COUNT(*) FROM dbc_signals
            WHERE signal_category IS NULL OR signal_category IN ('UNKNOWN', 'other')
        """)).scalar()
        
        sig_cat_unknown_pct_after = (sig_cat_unknown_after / sig_total * 100) if sig_total > 0 else 0
        click.echo(f"  DBC signals category UNKNOWN/other/NULL: {sig_cat_unknown_after:,} / {sig_total:,} ({sig_cat_unknown_pct_after:.1f}%)")
        
        # Summary
        click.echo()
        click.echo("=" * 80)
        cmd_reduction = cmd_unknown - cmd_unknown_after
        sig_ecu_reduction = sig_ecu_unknown - sig_ecu_unknown_after
        sig_cat_reduction = sig_cat_unknown - sig_cat_unknown_after
        
        click.echo(f"SUMMARY:")
        click.echo(f"  Commands ECU: {cmd_unknown:,} → {cmd_unknown_after:,} (-{cmd_reduction:,}, {cmd_unknown_pct:.1f}% → {cmd_unknown_pct_after:.1f}%)")
        click.echo(f"  Signals ECU: {sig_ecu_unknown:,} → {sig_ecu_unknown_after:,} (-{sig_ecu_reduction:,}, {sig_ecu_unknown_pct:.1f}% → {sig_ecu_unknown_pct_after:.1f}%)")
        click.echo(f"  Signals Category: {sig_cat_unknown:,} → {sig_cat_unknown_after:,} (-{sig_cat_reduction:,}, {sig_cat_unknown_pct:.1f}% → {sig_cat_unknown_pct_after:.1f}%)")
        click.echo("=" * 80)

    app.cli.add_command(definitions)
    
    @click.group()
    def wescan() -> None:
        """WESCAN command profiles and scan management."""
        pass
    
    @wescan.command("build-profiles")
    @click.option("--export", type=click.Path(), help="Export profiles to JSON file")
    def build_profiles(export: str | None) -> None:
        """Build WESCAN command profiles from diagnostic_commands.
        
        Profiles group commands by maker/model for reuse at scan time.
        
        Usage:
            flask wescan build-profiles               # Show coverage stats
            flask wescan build-profiles --export profiles.json  # Export to file
        """
        from app.modules.scanner.wescan_profiles import build_profiles, get_profile_coverage
        import json
        
        click.echo("=" * 80)
        click.echo("WESCAN COMMAND PROFILES")
        click.echo("=" * 80)
        click.echo()
        
        click.echo("Building profiles from diagnostic_commands...")
        profiles = build_profiles()
        
        click.echo("Getting coverage statistics...")
        coverage = get_profile_coverage()
        
        click.echo()
        click.echo("Coverage Statistics:")
        click.echo("-" * 80)
        click.echo(f"  Total makers with profiles: {coverage['total_makers']}")
        click.echo(f"  Total maker/model combinations: {coverage['total_models']}")
        click.echo(f"  Total commands: {coverage['total_commands']}")
        
        click.echo("\n  Top makers by command count:")
        for maker, count in sorted(coverage['commands_by_maker'].items(), 
                                   key=lambda x: x[1], reverse=True)[:10]:
            click.echo(f"    {maker}: {count} commands")
        
        click.echo("\n  Top ECU addresses:")
        for ecu, count in coverage['commands_by_ecu'].items():
            click.echo(f"    {ecu}: {count} commands")
        
        click.echo("\n  Source breakdown:")
        for source, count in coverage['top_sources']:
            click.echo(f"    {source}: {count} commands")
        
        if export:
            click.echo(f"\nExporting profiles to {export}...")
            with open(export, 'w', encoding='utf-8') as f:
                json.dump({
                    'profiles': profiles,
                    'coverage': coverage
                }, f, indent=2, ensure_ascii=False)
            click.echo("Export complete.")
        
        click.echo()
        click.echo("=" * 80)
        click.echo(f"Profile build complete: {coverage['total_makers']} makers, "
                  f"{coverage['total_models']} models, {coverage['total_commands']} commands")
        click.echo("=" * 80)
    
    app.cli.add_command(wescan)
    
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
