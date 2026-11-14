import os

import click
from flask import Flask
from flask.cli import AppGroup
from sqlalchemy import select, text

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
    @click.option("--report-only", is_flag=True, help="Show projected changes with samples (no DB changes)")
    @click.option("--revert", is_flag=True, help="Revert backfill using evidence column")
    @click.option("--yes", is_flag=True, help="Apply backfill without confirmation")
    def backfill_ecu(report_only: bool, revert: bool, yes: bool) -> None:
        """Backfill ECU module and signal category from explicit source file evidence ONLY.
        
        Evidence sources (NO keyword guessing):
        1. DBC BO_ transmitter node
        2. UDS/ISO-TP CAN ID explicitly associated with ECU in same source file
        3. File path that literally contains ECU name (/BMS/, _bms_, etc.)
        
        Usage:
            flask definitions backfill-ecu --report-only  # Show projected changes + samples
            flask definitions backfill-ecu --yes          # Apply backfill
            flask definitions backfill-ecu --revert --yes # Revert backfill
        """
        import json
        from sqlalchemy import text
        from app.modules.definitions.ecu_backfill import extract_ecu_from_evidence, extract_category_from_evidence
        from collections import defaultdict
        
        # Handle revert
        if revert:
            if not yes:
                click.echo("Reverting ECU/category backfill...")
                click.echo("This will restore values to their state before backfill using evidence.")
                if not click.confirm("\nProceed with revert?"):
                    click.echo("Aborted.")
                    return
            
            click.echo("=" * 80)
            click.echo("REVERTING ECU/CATEGORY BACKFILL")
            click.echo("=" * 80)
            
            # Revert commands
            cmd_reverted = db.session.execute(text("""
                UPDATE diagnostic_commands
                SET ecu_module = NULL, ecu_backfill_evidence = NULL
                WHERE ecu_backfill_evidence IS NOT NULL
            """)).rowcount
            
            # Revert signals ECU
            sig_ecu_reverted = db.session.execute(text("""
                UPDATE dbc_signals
                SET ecu_module = NULL, ecu_backfill_evidence = NULL
                WHERE ecu_backfill_evidence IS NOT NULL
            """)).rowcount
            
            # Revert signals category
            sig_cat_reverted = db.session.execute(text("""
                UPDATE dbc_signals
                SET signal_category = NULL, category_backfill_evidence = NULL
                WHERE category_backfill_evidence IS NOT NULL
            """)).rowcount
            
            db.session.commit()
            
            click.echo(f"\nReverted:")
            click.echo(f"  Commands ECU: {cmd_reverted}")
            click.echo(f"  Signals ECU: {sig_ecu_reverted}")
            click.echo(f"  Signals category: {sig_cat_reverted}")
            click.echo("=" * 80)
            return
        
        # Get current stats
        click.echo("=" * 80)
        click.echo("ECU/CATEGORY BACKFILL (Evidence-Based Only)")
        click.echo("=" * 80)
        click.echo()
        
        # BEFORE stats
        cmd_total = db.session.execute(text("SELECT COUNT(*) FROM diagnostic_commands")).scalar()
        cmd_unknown = db.session.execute(text("""
            SELECT COUNT(*) FROM diagnostic_commands
            WHERE ecu_module IS NULL OR ecu_module = 'UNKNOWN'
        """)).scalar()
        
        sig_total = db.session.execute(text("SELECT COUNT(*) FROM dbc_signals")).scalar()
        sig_ecu_unknown = db.session.execute(text("""
            SELECT COUNT(*) FROM dbc_signals
            WHERE ecu_module IS NULL OR ecu_module = 'UNKNOWN'
        """)).scalar()
        
        sig_cat_unknown = db.session.execute(text("""
            SELECT COUNT(*) FROM dbc_signals
            WHERE signal_category IS NULL OR signal_category IN ('UNKNOWN', 'other')
        """)).scalar()
        
        click.echo("BEFORE Backfill:")
        click.echo("-" * 80)
        cmd_pct = (cmd_unknown/cmd_total*100) if cmd_total > 0 else 0
        sig_ecu_pct = (sig_ecu_unknown/sig_total*100) if sig_total > 0 else 0
        sig_cat_pct = (sig_cat_unknown/sig_total*100) if sig_total > 0 else 0
        click.echo(f"  Commands ECU UNKNOWN/NULL: {cmd_unknown:,} / {cmd_total:,} ({cmd_pct:.1f}%)")
        click.echo(f"  DBC signals ECU UNKNOWN/NULL: {sig_ecu_unknown:,} / {sig_total:,} ({sig_ecu_pct:.1f}%)")
        click.echo(f"  DBC signals category UNKNOWN/other/NULL: {sig_cat_unknown:,} / {sig_total:,} ({sig_cat_pct:.1f}%)")
        click.echo()
        
        # Simulate backfill to get projections
        rule_counts = defaultdict(lambda: {'count': 0, 'samples': []})
        
        # 1. Scan commands for ECU
        commands = db.session.execute(text("""
            SELECT dc.id, dc.command_bytes, dc.label, ds.file_path
            FROM diagnostic_commands dc
            LEFT JOIN definition_sources ds ON dc.source_id = ds.id
            WHERE dc.ecu_module IS NULL OR dc.ecu_module = 'UNKNOWN'
        """)).fetchall()
        
        cmd_changes = []
        for cmd_id, cmd_bytes, label, file_path in commands:
            result = extract_ecu_from_evidence(
                file_path=file_path,
                command_bytes=cmd_bytes,
                dbc_sender_ecu=None
            )
            if result:
                ecu, evidence = result
                cmd_changes.append((cmd_id, ecu, evidence))
                rule = evidence['rule']
                rule_counts[f"commands_ecu_{rule}"]['count'] += 1
                if len(rule_counts[f"commands_ecu_{rule}"]['samples']) < 20:
                    rule_counts[f"commands_ecu_{rule}"]['samples'].append({
                        'id': cmd_id,
                        'label': label or '(no label)',
                        'ecu': ecu,
                        'matched': evidence['matched_text'][:80]
                    })
        
        # 2. Scan signals for ECU
        signals = db.session.execute(text("""
            SELECT ds.id, ds.signal_name, dm.sender, ds.comment, src.file_path
            FROM dbc_signals ds
            LEFT JOIN dbc_messages dm ON ds.message_id = dm.id
            LEFT JOIN definition_sources src ON dm.source_id = src.id
            WHERE ds.ecu_module IS NULL OR ds.ecu_module = 'UNKNOWN'
        """)).fetchall()
        
        sig_ecu_changes = []
        for sig_id, signal_name, sender_ecu, comment, file_path in signals:
            result = extract_ecu_from_evidence(
                file_path=file_path,
                dbc_sender_ecu=sender_ecu
            )
            if result:
                ecu, evidence = result
                sig_ecu_changes.append((sig_id, ecu, evidence))
                rule = evidence['rule']
                rule_counts[f"signals_ecu_{rule}"]['count'] += 1
                if len(rule_counts[f"signals_ecu_{rule}"]['samples']) < 20:
                    rule_counts[f"signals_ecu_{rule}"]['samples'].append({
                        'id': sig_id,
                        'name': signal_name or '(no name)',
                        'ecu': ecu,
                        'matched': evidence['matched_text'][:80]
                    })
        
        # 3. Scan signals for category
        signals_cat = db.session.execute(text("""
            SELECT ds.id, ds.signal_name, ds.comment, src.file_path
            FROM dbc_signals ds
            LEFT JOIN dbc_messages dm ON ds.message_id = dm.id
            LEFT JOIN definition_sources src ON dm.source_id = src.id
            WHERE ds.signal_category IS NULL OR ds.signal_category IN ('UNKNOWN', 'other')
        """)).fetchall()
        
        sig_cat_changes = []
        for sig_id, signal_name, comment, file_path in signals_cat:
            result = extract_category_from_evidence(
                file_path=file_path,
                dbc_comment=comment
            )
            if result:
                category, evidence = result
                sig_cat_changes.append((sig_id, category, evidence))
                rule = evidence['rule']
                rule_counts[f"signals_category_{rule}"]['count'] += 1
                if len(rule_counts[f"signals_category_{rule}"]['samples']) < 20:
                    rule_counts[f"signals_category_{rule}"]['samples'].append({
                        'id': sig_id,
                        'name': signal_name or '(no name)',
                        'category': category,
                        'matched': evidence['matched_text'][:80]
                    })
        
        # Show projections
        cmd_after = cmd_unknown - len(cmd_changes)
        sig_ecu_after = sig_ecu_unknown - len(sig_ecu_changes)
        sig_cat_after = sig_cat_unknown - len(sig_cat_changes)
        
        click.echo("PROJECTED After Backfill:")
        click.echo("-" * 80)
        click.echo(f"  Commands ECU: {cmd_unknown:,} → {cmd_after:,} (-{len(cmd_changes):,})")
        click.echo(f"  Signals ECU: {sig_ecu_unknown:,} → {sig_ecu_after:,} (-{len(sig_ecu_changes):,})")
        click.echo(f"  Signals category: {sig_cat_unknown:,} → {sig_cat_after:,} (-{len(sig_cat_changes):,})")
        click.echo()
        
        # Show per-rule counts
        if rule_counts:
            click.echo("Per-Rule Hit Counts:")
            click.echo("-" * 80)
            for rule_key in sorted(rule_counts.keys()):
                count = rule_counts[rule_key]['count']
                click.echo(f"  {rule_key}: {count}")
            click.echo()
            
            # Show samples
            click.echo("Sample Matches (up to 20 per rule):")
            click.echo("=" * 80)
            for rule_key in sorted(rule_counts.keys()):
                samples = rule_counts[rule_key]['samples']
                if samples:
                    click.echo(f"\n{rule_key} ({len(samples)} samples):")
                    click.echo("-" * 80)
                    for i, sample in enumerate(samples[:20], 1):
                        if 'ecu' in sample:
                            click.echo(f"  {i}. ID={sample['id']}, ECU={sample['ecu']}")
                            click.echo(f"     {sample.get('label') or sample.get('name')}")
                            click.echo(f"     Matched: {sample['matched']}")
                        else:
                            click.echo(f"  {i}. ID={sample['id']}, Category={sample['category']}")
                            click.echo(f"     {sample.get('name')}")
                            click.echo(f"     Matched: {sample['matched']}")
            click.echo("=" * 80)
        
        if report_only:
            click.echo("\n(Use --yes to apply these changes)")
            return
        
        if not yes:
            click.echo("\nThis will apply the changes shown above.")
            click.echo("Evidence will be stored in *_backfill_evidence columns for audit/revert.")
            if not click.confirm("\nProceed with backfill?"):
                click.echo("Aborted.")
                return
        
        # Apply changes
        click.echo("\nApplying backfill...")
        click.echo("-" * 80)
        
        # Apply command ECU updates
        for cmd_id, ecu, evidence in cmd_changes:
            db.session.execute(text("""
                UPDATE diagnostic_commands
                SET ecu_module = :ecu, ecu_backfill_evidence = :evidence
                WHERE id = :id
            """), {'id': cmd_id, 'ecu': ecu, 'evidence': json.dumps(evidence)})
        
        # Apply signal ECU updates
        for sig_id, ecu, evidence in sig_ecu_changes:
            db.session.execute(text("""
                UPDATE dbc_signals
                SET ecu_module = :ecu, ecu_backfill_evidence = :evidence
                WHERE id = :id
            """), {'id': sig_id, 'ecu': ecu, 'evidence': json.dumps(evidence)})
        
        # Apply signal category updates
        for sig_id, category, evidence in sig_cat_changes:
            db.session.execute(text("""
                UPDATE dbc_signals
                SET signal_category = :category, category_backfill_evidence = :evidence
                WHERE id = :id
            """), {'id': sig_id, 'category': category, 'evidence': json.dumps(evidence)})
        
        db.session.commit()
        
        click.echo(f"  Commands ECU: {len(cmd_changes)} updated")
        click.echo(f"  Signals ECU: {len(sig_ecu_changes)} updated")
        click.echo(f"  Signals category: {len(sig_cat_changes)} updated")
        click.echo()
        click.echo("=" * 80)
        click.echo("Backfill complete. Evidence stored in *_backfill_evidence columns.")
        click.echo("Use --revert to undo these changes.")
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
        if coverage.get('common_commands', 0) > 0:
            click.echo(f"  Common commands (SAE standard): {coverage['common_commands']}")
        
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
        
        # Show exclusion statistics
        excluded = coverage.get('excluded_stats', {})
        if excluded:
            click.echo()
            click.echo("Exclusion Report:")
            click.echo("-" * 80)
            total_db = excluded.get('total_in_db', 0)
            included = coverage['total_commands']
            common = coverage.get('common_commands', 0)
            total_excluded = total_db - included - common
            
            click.echo(f"  Total in DB: {total_db}")
            click.echo(f"  Included in profiles: {included}")
            click.echo(f"  Common (SAE standard): {common}")
            click.echo(f"  Excluded: {total_excluded}")
            click.echo(f"    - Null maker: {excluded.get('null_maker', 0)}")
            click.echo(f"    - Unresolved maker: {excluded.get('unresolved_maker', 0)}")
            click.echo(f"    - Missing required fields: {excluded.get('missing_fields', 0)}")
            
            # Show unresolved makers
            unresolved_list = excluded.get('unresolved_makers', [])
            if unresolved_list:
                click.echo(f"\n  Top unresolved makers (need aliases):")
                for maker, count in unresolved_list:
                    click.echo(f"    {repr(maker)}: {count} commands")
            
            by_source = excluded.get('by_source', {})
            if by_source:
                click.echo(f"\n  Excluded by source type:")
                for source, count in sorted(by_source.items(), key=lambda x: x[1], reverse=True):
                    click.echo(f"    {source}: {count}")
        
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
    
    @wescan.command("coverage")
    @click.option("--maker", help="Filter by maker name (supports aliases like 현대/Hyundai)")
    @click.option("--detail", is_flag=True, help="Show per-model breakdown")
    def wescan_coverage(maker: str | None, detail: bool) -> None:
        """Show WESCAN command profile coverage by maker/model.
        
        Usage:
            flask wescan coverage                    # Overall summary
            flask wescan coverage --maker 현대       # Filter by maker (alias-aware)
            flask wescan coverage --detail           # Per-model breakdown
        """
        from app.modules.scanner.wescan_profiles import get_profile_coverage
        from app.core.makers import resolve_maker
        
        click.echo("=" * 80)
        click.echo("WESCAN PROFILE COVERAGE REPORT")
        click.echo("=" * 80)
        click.echo()
        
        coverage = get_profile_coverage()
        
        # Overall summary
        click.echo("Overall Coverage:")
        click.echo("-" * 80)
        click.echo(f"  Total makers: {coverage['total_makers']}")
        click.echo(f"  Total maker/model combinations: {coverage['total_models']}")
        click.echo(f"  Total commands: {coverage['total_commands']}")
        if coverage.get('common_commands', 0) > 0:
            click.echo(f"  Common commands (SAE standard): {coverage['common_commands']}")
        click.echo()
        
        # Commands by maker
        click.echo("Commands by Maker:")
        click.echo("-" * 80)
        
        makers_sorted = sorted(coverage['commands_by_maker'].items(), 
                              key=lambda x: x[1], reverse=True)
        
        if maker:
            # Resolve maker filter to standard key
            resolved_filter = resolve_maker(maker)
            if resolved_filter:
                makers_sorted = [(m, c) for m, c in makers_sorted if m == resolved_filter]
            else:
                # Fallback to substring match
                makers_sorted = [(m, c) for m, c in makers_sorted if maker.lower() in m.lower()]
        
        for maker_name, count in makers_sorted:
            percentage = (count / coverage['total_commands'] * 100) if coverage['total_commands'] > 0 else 0
            click.echo(f"  {maker_name:20s}: {count:5d} commands ({percentage:5.1f}%)")
        
        # ECU breakdown
        click.echo()
        click.echo("Commands by ECU:")
        click.echo("-" * 80)
        for ecu, count in sorted(coverage['commands_by_ecu'].items(), key=lambda x: x[1], reverse=True):
            click.echo(f"  {ecu:10s}: {count:5d} commands")
        
        # Source breakdown
        click.echo()
        click.echo("Commands by Source:")
        click.echo("-" * 80)
        for source, count in coverage['top_sources']:
            click.echo(f"  {source:15s}: {count:5d} commands")
        
        # Detailed per-model breakdown
        if detail:
            click.echo()
            click.echo("Per-Model Breakdown:")
            click.echo("-" * 80)
            
            # Get per-model data
            model_data = db.session.execute(text("""
                SELECT maker, model, COUNT(*) as cmd_count
                FROM diagnostic_commands
                WHERE maker IS NOT NULL
                GROUP BY maker, model
                ORDER BY maker, model
            """)).fetchall()
            
            current_maker = None
            for maker_name, model_name, cmd_count in model_data:
                if maker and maker.lower() not in maker_name.lower():
                    continue
                
                if maker_name != current_maker:
                    click.echo(f"\n  {maker_name}:")
                    current_maker = maker_name
                
                model_display = model_name or 'generic'
                click.echo(f"    {model_display:30s}: {cmd_count:4d} commands")
        
        click.echo()
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

    # Learning management commands
    @click.group()
    def learning() -> None:
        """Continuous learning management and experiment tracking."""
        pass
    
    @learning.command("stats")
    @click.option("--maker", help="Filter by maker")
    @click.option("--model", help="Filter by model")
    @click.option("--ecu", help="Filter by ECU")
    @click.option("--limit", default=20, help="Limit results")
    def learning_stats(maker: str, model: str, ecu: str, limit: int) -> None:
        """Show learning statistics from command_stats."""
        from sqlalchemy import text
        
        query = """
            SELECT maker, model, ecu, command, attempts, successes, 
                   ROUND(100.0 * successes / NULLIF(attempts, 0), 1) as success_rate,
                   avg_response_ms, ucb_score, last_seen
            FROM command_stats
            WHERE 1=1
        """
        params = {}
        
        if maker:
            query += " AND maker = :maker"
            params['maker'] = maker
        if model:
            query += " AND model = :model"
            params['model'] = model
        if ecu:
            query += " AND ecu = :ecu"
            params['ecu'] = ecu
        
        query += f" ORDER BY ucb_score DESC NULLS LAST LIMIT {limit}"
        
        results = db.session.execute(text(query), params).fetchall()
        
        click.echo("=" * 120)
        click.echo("LEARNING STATISTICS (Top by UCB Score)")
        click.echo("=" * 120)
        click.echo(f"{'Maker':<15} {'Model':<20} {'ECU':<10} {'Command':<15} {'Attempts':<10} {'Success%':<10} {'AvgMs':<10} {'UCB':<8}")
        click.echo("-" * 120)
        
        for row in results:
            maker_val, model_val, ecu_val, cmd, attempts, successes, rate, avg_ms, ucb, last = row
            avg_str = f"{int(avg_ms)}" if avg_ms else "N/A"
            ucb_str = f"{ucb:.3f}" if ucb else "N/A"
            click.echo(f"{maker_val:<15} {model_val or 'N/A':<20} {ecu_val:<10} {cmd:<15} {attempts:<10} {rate or 0:<10.1f} {avg_str:<10} {ucb_str:<8}")
        
        click.echo("=" * 120)
    
    @learning.command("promote")
    @click.argument("run_id", type=int)
    @click.option("--yes", is_flag=True, help="Skip confirmation")
    def learning_promote(run_id: int, yes: bool) -> None:
        """Promote a learning run to production."""
        from sqlalchemy import text
        
        # Get run info
        run = db.session.execute(text("""
            SELECT id, run_name, status, params, metrics
            FROM learning_runs WHERE id = :id
        """), {'id': run_id}).fetchone()
        
        if not run:
            click.echo(f"Learning run {run_id} not found", err=True)
            return
        
        if run[2] == 'promoted':
            click.echo(f"Run {run_id} is already promoted", err=True)
            return
        
        click.echo(f"Run ID: {run[0]}")
        click.echo(f"Name: {run[1]}")
        click.echo(f"Status: {run[2]}")
        click.echo(f"Params: {run[3]}")
        click.echo(f"Metrics: {run[4]}")
        
        if not yes:
            if not click.confirm("\nPromote this run to production?"):
                click.echo("Aborted")
                return
        
        db.session.execute(text("""
            UPDATE learning_runs 
            SET status = 'promoted', promoted_at = now(), updated_at = now()
            WHERE id = :id
        """), {'id': run_id})
        db.session.commit()
        
        click.echo(f"✓ Run {run_id} promoted to production")
    
    @learning.command("rollback")
    @click.argument("run_id", type=int)
    @click.option("--reason", required=True, help="Reason for rollback")
    @click.option("--yes", is_flag=True, help="Skip confirmation")
    def learning_rollback(run_id: int, reason: str, yes: bool) -> None:
        """Roll back a learning run."""
        from sqlalchemy import text
        
        run = db.session.execute(text("""
            SELECT id, run_name, status FROM learning_runs WHERE id = :id
        """), {'id': run_id}).fetchone()
        
        if not run:
            click.echo(f"Learning run {run_id} not found", err=True)
            return
        
        click.echo(f"Rolling back run {run[0]}: {run[1]} (status: {run[2]})")
        click.echo(f"Reason: {reason}")
        
        if not yes:
            if not click.confirm("\nProceed with rollback?"):
                click.echo("Aborted")
                return
        
        db.session.execute(text("""
            UPDATE learning_runs 
            SET status = 'rolled_back', rolled_back_at = now(), 
                rollback_reason = :reason, updated_at = now()
            WHERE id = :id
        """), {'id': run_id, 'reason': reason})
        db.session.commit()
        
        click.echo(f"✓ Run {run_id} rolled back")
    
    app.cli.add_command(learning)
    
    @definitions.command("reimport-canze-names")
    @click.option("--report-only", is_flag=True, help="Show what would change without modifying data")
    @click.option("--yes", is_flag=True, help="Apply changes without confirmation")
    @click.option("--revert", is_flag=True, help="Revert previous changes from database")
    def reimport_canze_names(report_only: bool, yes: bool, revert: bool) -> None:
        """Re-import CanZE field names from source CSV files with correct column index.
        
        Fixes parsing error where hex values (ff, 4ff) were imported as names
        instead of actual field names from column 11.
        
        Uses 1:1 matching: (source_id, ecu_address, command_bytes, response_start_byte, response_bit_offset)
        
        Usage:
            flask definitions reimport-canze-names --report-only  # Preview changes
            flask definitions reimport-canze-names --yes          # Apply fixes
            flask definitions reimport-canze-names --revert --yes # Undo last changes
        """
        from pathlib import Path
        from app.modules.definitions.models import DefinitionSource, DiagnosticCommand
        import csv
        
        click.echo("=" * 80)
        click.echo("CANZE FIELD NAME RE-IMPORT")
        click.echo("=" * 80)
        click.echo()
        
        if revert:
            click.echo("REVERT MODE: Restoring previous labels from database")
            click.echo()
            
            # Find unrever ted changes in label_change_history
            history = db.session.execute(text("""
                SELECT id, command_id, old_label, new_label
                FROM label_change_history
                WHERE operation = 'canze_reimport' AND reverted_at IS NULL
                ORDER BY changed_at DESC
            """)).fetchall()
            
            if not history:
                click.echo("✗ No revert data found. Run with --yes first.", err=True)
                return
            
            click.echo(f"Found {len(history)} records to revert")
            click.echo()
            click.echo("Sample reverts (first 10):")
            click.echo("-" * 80)
            for h in history[:10]:
                click.echo(f"  ID {h[1]}: '{h[3]}' → '{h[2]}'")
            click.echo()
            
            if not yes:
                if not click.confirm(f"Revert {len(history)} label changes?"):
                    click.echo("Aborted.")
                    return
            
            click.echo()
            click.echo("Reverting changes...")
            reverted = 0
            
            for h in history:
                # Restore old label
                db.session.execute(text("""
                    UPDATE diagnostic_commands
                    SET label = :old_label, updated_at = now()
                    WHERE id = :cmd_id
                """), {'old_label': h[2], 'cmd_id': h[1]})
                
                # Mark as reverted
                db.session.execute(text("""
                    UPDATE label_change_history
                    SET reverted_at = now()
                    WHERE id = :history_id
                """), {'history_id': h[0]})
                reverted += 1
            
            db.session.commit()
            
            click.echo(f"✓ Reverted {reverted} label changes")
            click.echo("=" * 80)
            return
        
        click.echo("Corrects column index: row[10] → row[11] for field name")
        click.echo("CanZE format: sid, ID, startBit, endBit, resolution, offset, decimals, unit,")
        click.echo("              requestId, responseId, options, name, ...")
        click.echo()
        click.echo("Matching strategy: 1:1 by (source_id, ecu, command, startBit, endBit)")
        click.echo()
        
        # Find all CanZE sources
        canze_sources = db.session.query(DefinitionSource).filter_by(source_type='canze').all()
        
        if not canze_sources:
            click.echo("No CanZE sources found in database.")
            return
        
        click.echo(f"Found {len(canze_sources)} CanZE source(s)")
        click.echo()
        
        changes = []
        skipped_multiple = []
        skipped_none = []
        errors = []
        
        for source in canze_sources:
            file_path = Path(source.file_path)
            
            if not file_path.exists():
                errors.append(f"File not found: {file_path}")
                continue
            
            click.echo(f"Processing: {file_path}")
            
            # Read CSV with correct column
            try:
                with open(file_path, 'r', encoding='utf-8-sig') as f:
                    reader = csv.reader(f)
                    for row_idx, row in enumerate(reader):
                        if len(row) >= 12 and row[1] and row[8]:
                            ecu_address = row[1]
                            request_id = row[8]
                            start_bit = row[2] if len(row) > 2 else None
                            end_bit = row[3] if len(row) > 3 else None
                            correct_name = row[11]
                            
                            # Convert bit positions to byte/offset for matching
                            # CanZE uses bit positions, DB uses byte + bit_offset
                            try:
                                start_byte = int(start_bit) // 8 if start_bit else None
                                bit_offset = int(start_bit) % 8 if start_bit else None
                            except (ValueError, TypeError):
                                start_byte = None
                                bit_offset = None
                            
                            # Find corresponding command(s) with exact match
                            candidates = db.session.query(DiagnosticCommand).filter_by(
                                source_id=source.id,
                                command_bytes=request_id,
                                ecu_address=ecu_address
                            )
                            
                            # Further filter by response position if available
                            if start_byte is not None:
                                candidates = candidates.filter_by(response_start_byte=start_byte)
                            if bit_offset is not None:
                                candidates = candidates.filter_by(response_bit_offset=bit_offset)
                            
                            candidates_list = candidates.all()
                            
                            if len(candidates_list) == 0:
                                skipped_none.append(f"Row {row_idx}: {ecu_address} {request_id} bit {start_bit}-{end_bit}")
                            elif len(candidates_list) > 1:
                                skipped_multiple.append(f"Row {row_idx}: {ecu_address} {request_id} bit {start_bit}-{end_bit} ({len(candidates_list)} matches)")
                            else:
                                cmd = candidates_list[0]
                                if cmd.label != correct_name:
                                    changes.append({
                                        'cmd_id': cmd.id,
                                        'ecu': ecu_address,
                                        'command': request_id,
                                        'position': f"{start_bit}-{end_bit}",
                                        'old_label': cmd.label,
                                        'new_label': correct_name
                                    })
            except Exception as e:
                errors.append(f"Error reading {file_path}: {str(e)}")
        
        # Report
        click.echo()
        click.echo("=" * 80)
        click.echo(f"SUMMARY: {len(changes)} changes, {len(skipped_multiple)} multi-match, {len(skipped_none)} no-match")
        click.echo("=" * 80)
        
        if changes:
            click.echo()
            click.echo("Sample changes (first 20):")
            click.echo("-" * 80)
            for change in changes[:20]:
                click.echo(f"  {change['ecu']} {change['command']} bit{change['position']}: '{change['old_label']}' → '{change['new_label']}'")
        
        if skipped_multiple:
            click.echo()
            click.echo(f"Skipped {len(skipped_multiple)} multi-match rows (first 10):")
            for skip in skipped_multiple[:10]:
                click.echo(f"  {skip}")
        
        if skipped_none:
            click.echo()
            click.echo(f"Skipped {len(skipped_none)} no-match rows (first 10):")
            for skip in skipped_none[:10]:
                click.echo(f"  {skip}")
        
        if errors:
            click.echo()
            click.echo("Errors:")
            for err in errors:
                click.echo(f"  ✗ {err}", err=True)
        
        click.echo()
        click.echo("=" * 80)
        
        if report_only:
            click.echo("(Use --yes to apply these changes)")
            return
        
        if not changes:
            click.echo("No changes needed.")
            return
        
        if not yes:
            click.echo()
            if not click.confirm(f"Apply {len(changes)} name corrections?"):
                click.echo("Aborted.")
                return
        
        # Apply changes
        click.echo()
        click.echo("Applying changes...")
        
        updated = 0
        for change in changes:
            # Save to history
            db.session.execute(text("""
                INSERT INTO label_change_history (command_id, old_label, new_label, operation)
                VALUES (:cmd_id, :old_label, :new_label, 'canze_reimport')
            """), {
                'cmd_id': change['cmd_id'],
                'old_label': change['old_label'],
                'new_label': change['new_label']
            })
            
            # Update label
            db.session.execute(text("""
                UPDATE diagnostic_commands
                SET label = :new_label, updated_at = now()
                WHERE id = :cmd_id
            """), {'new_label': change['new_label'], 'cmd_id': change['cmd_id']})
            updated += 1
        
        db.session.commit()
        
        click.echo(f"✓ Updated {updated} command names")
        click.echo("✓ Revert data saved to label_change_history table")
        click.echo("  (Use --revert --yes to undo these changes)")
        click.echo("=" * 80)
    
    # Battery specs CLI
    battery = AppGroup("battery", help="Battery specification management")
    
    @battery.command("check-sources")
    @click.option("--detail", is_flag=True, help="Show per-maker breakdown")
    def check_battery_sources(detail: bool) -> None:
        """Check battery_specs source URL coverage and quality.
        
        Verifies that all battery specs have proper source citations.
        Reports coverage, source types, and missing citations.
        
        Usage:
            flask battery check-sources           # Overall summary
            flask battery check-sources --detail  # Per-maker breakdown
        """
        from app.modules.battery.models import BatterySpec
        
        click.echo("=" * 80)
        click.echo("BATTERY SPECS SOURCE VERIFICATION")
        click.echo("=" * 80)
        click.echo()
        
        # Overall statistics
        total = db.session.query(BatterySpec).count()
        with_url = db.session.query(BatterySpec).filter(
            BatterySpec.source_url != None,
            BatterySpec.source_url != ''
        ).count()
        
        manufacturer = db.session.query(BatterySpec).filter(
            BatterySpec.source_type == 'manufacturer'
        ).count()
        
        third_party = db.session.query(BatterySpec).filter(
            BatterySpec.source_type == 'third_party'
        ).count()
        
        null_type = db.session.query(BatterySpec).filter(
            BatterySpec.source_type == None
        ).count()
        
        click.echo("Overall Coverage:")
        click.echo("-" * 80)
        click.echo(f"  Total battery specs: {total}")
        url_pct = (with_url/total*100) if total > 0 else 0
        click.echo(f"  With source URL: {with_url} ({url_pct:.1f}%)")
        click.echo(f"  Missing URL: {total - with_url}")
        click.echo()
        
        click.echo("Source Type Distribution:")
        click.echo("-" * 80)
        mfr_pct = (manufacturer/total*100) if total > 0 else 0
        tp_pct = (third_party/total*100) if total > 0 else 0
        click.echo(f"  Manufacturer (official): {manufacturer} ({mfr_pct:.1f}%)")
        click.echo(f"  Third-party: {third_party} ({tp_pct:.1f}%)")
        click.echo(f"  Unclassified: {null_type}")
        click.echo()
        
        # Top sources
        top_sources = db.session.execute(text("""
            SELECT source_url, COUNT(*) as count
            FROM battery_specs
            WHERE source_url IS NOT NULL AND source_url != ''
            GROUP BY source_url
            ORDER BY count DESC
            LIMIT 10
        """)).fetchall()
        
        click.echo("Top Source URLs:")
        click.echo("-" * 80)
        for url, count in top_sources:
            # Truncate long URLs
            display_url = url if len(url) <= 60 else url[:57] + "..."
            click.echo(f"  {count:3d}x {display_url}")
        
        # Missing data analysis
        click.echo()
        click.echo("Data Completeness:")
        click.echo("-" * 80)
        
        fields = [
            ('gross_kwh', 'Gross capacity (kWh)'),
            ('usable_kwh', 'Usable capacity (kWh)'),
            ('capacity_ah', 'Capacity (Ah)'),
            ('nominal_voltage_v', 'Nominal voltage (V)'),
            ('cell_chemistry', 'Cell chemistry'),
            ('cell_count', 'Cell count')
        ]
        
        for field, label in fields:
            filled = db.session.execute(text(f"""
                SELECT COUNT(*) FROM battery_specs WHERE {field} IS NOT NULL
            """)).scalar()
            fill_pct = (filled/total*100) if total > 0 else 0
            click.echo(f"  {label:25s}: {filled:3d}/{total} ({fill_pct:.1f}%)")
        
        # Per-maker breakdown
        if detail:
            click.echo()
            click.echo("Per-Maker Breakdown:")
            click.echo("-" * 80)
            
            makers = db.session.execute(text("""
                SELECT 
                    maker,
                    COUNT(*) as total,
                    SUM(CASE WHEN source_url IS NOT NULL AND source_url != '' THEN 1 ELSE 0 END) as with_url,
                    SUM(CASE WHEN source_type = 'manufacturer' THEN 1 ELSE 0 END) as manufacturer,
                    SUM(CASE WHEN source_type = 'third_party' THEN 1 ELSE 0 END) as third_party
                FROM battery_specs
                GROUP BY maker
                ORDER BY total DESC
            """)).fetchall()
            
            for maker, total, with_url, mfr, tp in makers:
                click.echo(f"\n  {maker}:")
                click.echo(f"    Total specs: {total}")
                url_pct = (with_url/total*100) if total > 0 else 0
                click.echo(f"    With URL: {with_url}/{total} ({url_pct:.1f}%)")
                click.echo(f"    Official: {mfr}, Third-party: {tp}")
        
        click.echo()
        click.echo("=" * 80)
        click.echo("Recommendation:")
        if total - with_url > 0:
            click.echo(f"  ⚠ {total - with_url} specs missing source URL - should be cited or removed")
        if null_type > 0:
            click.echo(f"  ⚠ {null_type} specs need source_type classification (manufacturer/third_party)")
        if total - with_url == 0 and null_type == 0:
            click.echo("  ✓ All specs have proper source citations")
        click.echo("=" * 80)
    
    app.cli.add_command(battery)
