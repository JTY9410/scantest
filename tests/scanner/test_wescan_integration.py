"""Integration tests for WESCAN build-profiles E2E flow."""
import pytest
import json
import uuid
from pathlib import Path
from sqlalchemy import text
from app.extensions import db


@pytest.fixture
def wescan_test_commands(app):
    """Create test diagnostic commands for WESCAN profiling."""
    with app.app_context():
        # Generate unique identifiers for this test run
        unique_id = str(uuid.uuid4())[:8]
        sha_hash = uuid.uuid4().hex + uuid.uuid4().hex[:32]
        file_path = f'/test/wescan_test_{unique_id}.dbc'
        
        # Create definition source
        db.session.execute(text("""
            INSERT INTO definition_sources (source_type, file_path, sha256, file_size, imported_at)
            VALUES ('canze', :path, :sha, 100, NOW())
        """), {'path': file_path, 'sha': sha_hash})
        db.session.commit()
        
        source_id = db.session.execute(text("""
            SELECT id FROM definition_sources WHERE file_path = :path
        """), {'path': file_path}).scalar()
        
        # Create diagnostic commands for different makers/models
        db.session.execute(text("""
            INSERT INTO diagnostic_commands 
                (source_id, source_type, maker, model, ecu_address, service, pid, command_bytes, label,
                 formula, unit, verification_status, verification_count, success_count, failure_count,
                 created_at, updated_at)
            VALUES 
                (:sid, 'canze', '현대', 'Ioniq 5', '7E4', '22', '1050', '221050', 'SOC', 'A/2', '%', 'verified', 0, 0, 0, now(), now()),
                (:sid, 'canze', '현대', 'Ioniq 5', '7E4', '22', '1051', '221051', 'Battery Voltage', 'A*0.1', 'V', 'verified', 0, 0, 0, now(), now()),
                (:sid, 'canze', '현대', 'Ioniq 6', '7E4', '22', '1050', '221050', 'SOC', 'A/2', '%', 'verified', 0, 0, 0, now(), now()),
                (:sid, 'canze', '기아', 'EV6', '7E4', '22', '1050', '221050', 'SOC', 'A/2', '%', 'verified', 0, 0, 0, now(), now()),
                (:sid, 'canze', '기아', 'EV6', '7E2', '22', '1060', '221060', 'Speed', 'A', 'km/h', 'verified', 0, 0, 0, now(), now())
        """), {'sid': source_id})
        db.session.commit()
        
        yield {'source_id': source_id, 'file_path': file_path}
        
        # Cleanup
        db.session.execute(text("""
            DELETE FROM diagnostic_commands WHERE source_id = :sid
        """), {'sid': source_id})
        db.session.execute(text("""
            DELETE FROM definition_sources WHERE file_path = :path
        """), {'path': file_path})
        db.session.commit()


def test_wescan_build_profiles_cli(app, wescan_test_commands):
    """Test that flask wescan build-profiles executes successfully."""
    with app.app_context():
        runner = app.test_cli_runner()
        result = runner.invoke(args=['wescan', 'build-profiles'])
        
        assert result.exit_code == 0
        assert 'WESCAN COMMAND PROFILES' in result.output
        assert 'Building profiles from diagnostic_commands' in result.output
        assert 'Coverage Statistics' in result.output
        assert 'Total makers with profiles:' in result.output
        assert 'Profile build complete:' in result.output


def test_wescan_build_profiles_with_export(app, wescan_test_commands, tmp_path):
    """Test WESCAN profile export to JSON."""
    with app.app_context():
        export_file = tmp_path / "wescan_profiles.json"
        
        runner = app.test_cli_runner()
        result = runner.invoke(args=['wescan', 'build-profiles', '--export', str(export_file)])
        
        assert result.exit_code == 0
        assert export_file.exists()
        
        # Load and verify JSON structure
        with open(export_file, 'r') as f:
            data = json.load(f)
        
        assert 'profiles' in data
        assert 'coverage' in data
        
        # Verify profiles structure
        profiles = data['profiles']
        # Makers are now resolved to standard keys (hyundai, kia)
        assert 'hyundai' in profiles or 'kia' in profiles
        
        # Verify coverage structure
        coverage = data['coverage']
        assert 'total_makers' in coverage
        assert 'total_models' in coverage
        assert 'total_commands' in coverage
        assert coverage['total_commands'] >= 5  # At least our test commands


def test_wescan_profile_coverage_report(app, wescan_test_commands):
    """Test WESCAN coverage statistics calculation."""
    with app.app_context():
        from app.modules.scanner.wescan_profiles import get_profile_coverage
        
        coverage = get_profile_coverage()
        
        assert 'total_makers' in coverage
        assert 'total_models' in coverage
        assert 'total_commands' in coverage
        assert 'commands_by_maker' in coverage
        assert 'commands_by_ecu' in coverage
        
        # Our test data should be included
        assert coverage['total_makers'] >= 2  # At least hyundai and kia (resolved)
        assert coverage['total_commands'] >= 5
        
        # Check maker breakdown (makers are now resolved to standard keys)
        assert 'hyundai' in coverage['commands_by_maker'] or 'kia' in coverage['commands_by_maker']


def test_wescan_build_profiles_function(app, wescan_test_commands):
    """Test WESCAN build_profiles function directly."""
    with app.app_context():
        from app.modules.scanner.wescan_profiles import build_profiles
        
        profiles = build_profiles()
        
        # Verify structure
        assert isinstance(profiles, dict)
        
        # Should have our test makers
        assert len(profiles) >= 2
        
        # Check 현대 profile
        if '현대' in profiles:
            hyundai = profiles['현대']
            assert 'Ioniq 5' in hyundai or 'Ioniq 6' in hyundai
            
            if 'Ioniq 5' in hyundai:
                ioniq5 = hyundai['Ioniq 5']
                assert '7E4' in ioniq5
                
                commands = ioniq5['7E4']
                assert '22_1050' in commands or '22_1051' in commands
                
                if '22_1050' in commands:
                    cmd = commands['22_1050']
                    assert cmd['label'] == 'SOC'
                    assert cmd['command_bytes'] == '221050'
                    assert cmd['formula'] == 'A/2'
                    assert cmd['unit'] == '%'


def test_wescan_coverage_cli(app, wescan_test_commands):
    """Test flask wescan coverage command."""
    with app.app_context():
        runner = app.test_cli_runner()
        result = runner.invoke(args=['wescan', 'coverage'])
        
        assert result.exit_code == 0
        assert 'WESCAN PROFILE COVERAGE REPORT' in result.output
        assert 'Overall Coverage:' in result.output
        assert 'Total makers:' in result.output
        assert 'Commands by Maker:' in result.output


def test_wescan_coverage_with_maker_filter(app, wescan_test_commands):
    """Test flask wescan coverage --maker filter."""
    with app.app_context():
        runner = app.test_cli_runner()
        
        # Should work with Korean name
        result = runner.invoke(args=['wescan', 'coverage', '--maker', '현대'])
        assert result.exit_code == 0
        
        # Should work with English name (via maker_aliases)
        result2 = runner.invoke(args=['wescan', 'coverage', '--maker', 'Hyundai'])
        assert result2.exit_code == 0


def test_wescan_coverage_detail(app, wescan_test_commands):
    """Test flask wescan coverage --detail."""
    with app.app_context():
        runner = app.test_cli_runner()
        result = runner.invoke(args=['wescan', 'coverage', '--detail'])
        
        assert result.exit_code == 0
        assert 'Per-Model Breakdown:' in result.output


def test_battery_check_sources_cli(app):
    """Test flask battery check-sources command."""
    with app.app_context():
        runner = app.test_cli_runner()
        result = runner.invoke(args=['battery', 'check-sources'])
        
        assert result.exit_code == 0
        assert 'BATTERY SPECS SOURCE VERIFICATION' in result.output
        assert 'Overall Coverage:' in result.output
        assert 'Source Type Distribution:' in result.output
        assert 'Data Completeness:' in result.output


def test_battery_check_sources_detail(app):
    """Test flask battery check-sources --detail."""
    with app.app_context():
        runner = app.test_cli_runner()
        result = runner.invoke(args=['battery', 'check-sources', '--detail'])
        
        assert result.exit_code == 0
        assert 'Per-Maker Breakdown:' in result.output


def test_wescan_build_profiles_export_integration(app, wescan_test_commands, tmp_path):
    """Test complete flask wescan build-profiles --export flow."""
    with app.app_context():
        export_file = tmp_path / "test_profiles.json"
        
        runner = app.test_cli_runner()
        result = runner.invoke(args=['wescan', 'build-profiles', '--export', str(export_file)])
        
        assert result.exit_code == 0
        assert export_file.exists()
        
        # Verify JSON is valid and has expected structure
        with open(export_file, 'r') as f:
            data = json.load(f)
        
        assert 'profiles' in data
        assert 'coverage' in data
        assert isinstance(data['profiles'], dict)
        assert isinstance(data['coverage'], dict)


def test_canze_vehicle_definitions_join(app):
    """Test that canze commands with NULL maker use vehicle_definitions."""
    with app.app_context():
        from app.modules.scanner.wescan_profiles import build_profiles, get_profile_coverage
        
        # Create unique identifiers
        unique_id = str(uuid.uuid4())[:8]
        sha_hash = uuid.uuid4().hex + uuid.uuid4().hex[:32]
        file_path = f'/test/canze_vd_{unique_id}.csv'
        
        # Create definition source (canze type)
        db.session.execute(text("""
            INSERT INTO definition_sources (source_type, file_path, sha256, file_size, imported_at)
            VALUES ('canze', :path, :sha, 100, NOW())
        """), {'path': file_path, 'sha': sha_hash})
        db.session.commit()
        
        source_id = db.session.execute(text("""
            SELECT id FROM definition_sources WHERE file_path = :path
        """), {'path': file_path}).scalar()
        
        # Create vehicle_definition with maker/model
        db.session.execute(text("""
            INSERT INTO vehicle_definitions (source_id, maker, model, year_from, year_to, submodel, created_at)
            VALUES (:sid, 'Renault', 'ZOE', 2019, 2023, 'R135', NOW())
        """), {'sid': source_id})
        db.session.commit()
        
        # Create diagnostic command with NULL maker (typical for canze)
        db.session.execute(text("""
            INSERT INTO diagnostic_commands 
                (source_id, source_type, maker, model, ecu_address, service, pid, 
                 command_bytes, label, formula, unit, verification_status,
                 verification_count, success_count, failure_count,
                 created_at, updated_at)
            VALUES 
                (:sid, 'canze', NULL, NULL, '7BB', '22', '2002', '222002', 
                 'Battery SOC', 'A/2', '%', 'verified', 0, 0, 0, now(), now())
        """), {'sid': source_id})
        db.session.commit()
        
        # Build profiles should include this command via vehicle_definitions join
        profiles = build_profiles()
        coverage = get_profile_coverage()
        
        # Should be included under 'renault' (resolved from 'Renault')
        assert 'renault' in profiles
        assert coverage['total_commands'] >= 1
        
        # Verify in coverage stats
        assert 'renault' in coverage['commands_by_maker']


def test_wican_null_ecu_address(app):
    """Test that wican commands with NULL ecu_address are included."""
    with app.app_context():
        from app.modules.scanner.wescan_profiles import build_profiles, get_profile_coverage
        
        # Create unique identifiers
        unique_id = str(uuid.uuid4())[:8]
        sha_hash = uuid.uuid4().hex + uuid.uuid4().hex[:32]
        file_path = f'/test/wican_{unique_id}.json'
        
        # Create definition source (wican type)
        db.session.execute(text("""
            INSERT INTO definition_sources (source_type, file_path, sha256, file_size, imported_at)
            VALUES ('wican', :path, :sha, 100, NOW())
        """), {'path': file_path, 'sha': sha_hash})
        db.session.commit()
        
        source_id = db.session.execute(text("""
            SELECT id FROM definition_sources WHERE file_path = :path
        """), {'path': file_path}).scalar()
        
        # Create diagnostic command with NULL ecu_address (typical for wican)
        db.session.execute(text("""
            INSERT INTO diagnostic_commands 
                (source_id, source_type, maker, model, ecu_address, service, pid, 
                 command_bytes, label, formula, unit, verification_status,
                 verification_count, success_count, failure_count,
                 created_at, updated_at)
            VALUES 
                (:sid, 'wican', 'Renault_ Kangoo Z.E', 'Renault: Kangoo Z.E.', NULL, 
                 '22', '1234', '221234', 'Test Field', 'A', '', 'verified', 0, 0, 0, now(), now())
        """), {'sid': source_id})
        db.session.commit()
        
        # Build profiles should include this command with 'unknown' ECU
        profiles = build_profiles()
        coverage = get_profile_coverage()
        
        # Should be included under 'renault' (resolved from 'Renault_ Kangoo Z.E')
        assert 'renault' in profiles
        
        # Should have 'unknown' ECU in coverage
        assert 'unknown' in coverage['commands_by_ecu']
        assert coverage['commands_by_ecu']['unknown'] >= 1


def test_common_pid_separation(app):
    """Test that 공통규격 commands are separated into _common section."""
    with app.app_context():
        from app.modules.scanner.wescan_profiles import build_profiles, get_profile_coverage
        
        # Create unique identifiers
        unique_id = str(uuid.uuid4())[:8]
        sha_hash = uuid.uuid4().hex + uuid.uuid4().hex[:32]
        file_path = f'/test/common_{unique_id}.dbc'
        
        # Create definition source
        db.session.execute(text("""
            INSERT INTO definition_sources (source_type, file_path, sha256, file_size, imported_at)
            VALUES ('obdb', :path, :sha, 100, NOW())
        """), {'path': file_path, 'sha': sha_hash})
        db.session.commit()
        
        source_id = db.session.execute(text("""
            SELECT id FROM definition_sources WHERE file_path = :path
        """), {'path': file_path}).scalar()
        
        # Create common/standard PID command
        db.session.execute(text("""
            INSERT INTO diagnostic_commands 
                (source_id, source_type, maker, model, ecu_address, service, pid, 
                 command_bytes, label, formula, unit, verification_status,
                 verification_count, success_count, failure_count,
                 created_at, updated_at)
            VALUES 
                (:sid, 'obdb', '공통규격', NULL, '7E0', '01', '0C', '010C', 
                 'Engine RPM', '((A*256)+B)/4', 'rpm', 'verified', 0, 0, 0, now(), now())
        """), {'sid': source_id})
        db.session.commit()
        
        # Build profiles should include this in _common section
        profiles = build_profiles()
        coverage = get_profile_coverage()
        
        # Should be in _common section, not in regular makers
        assert '_common' in profiles
        assert '공통규격' not in profiles
        
        # Should be counted as common commands
        assert coverage['common_commands'] >= 1


def test_nissan_infiniti_alias(app):
    """Test that NissanInfiniti resolves to nissan."""
    with app.app_context():
        from app.core.makers import resolve_maker
        from app.modules.scanner.wescan_profiles import build_profiles, get_profile_coverage
        
        # Ensure NissanInfiniti alias exists in DB
        db.session.execute(text("""
            INSERT INTO maker_aliases (standard_key, english_name, korean_name, aliases)
            VALUES ('nissan', 'Nissan', '닛산', ARRAY['nissan', 'NissanInfiniti', 'nissaninfiniti', '닛산', '닛싼'])
            ON CONFLICT (standard_key) DO UPDATE SET
                aliases = EXCLUDED.aliases
        """))
        db.session.commit()
        
        # Clear cache to force reload
        import app.core.makers as makers_module
        makers_module._ALIASES_CACHE = None
        makers_module._REVERSE_LOOKUP_CACHE = None
        
        # Create unique identifiers
        unique_id = str(uuid.uuid4())[:8]
        sha_hash = uuid.uuid4().hex + uuid.uuid4().hex[:32]
        file_path = f'/test/nissaninfiniti_{unique_id}.dbc'
        
        # Create definition source
        db.session.execute(text("""
            INSERT INTO definition_sources (source_type, file_path, sha256, file_size, imported_at)
            VALUES ('obdb', :path, :sha, 100, NOW())
        """), {'path': file_path, 'sha': sha_hash})
        db.session.commit()
        
        source_id = db.session.execute(text("""
            SELECT id FROM definition_sources WHERE file_path = :path
        """), {'path': file_path}).scalar()
        
        # Create diagnostic command with NissanInfiniti maker
        db.session.execute(text("""
            INSERT INTO diagnostic_commands 
                (source_id, source_type, maker, model, ecu_address, service, pid, 
                 command_bytes, label, formula, unit, verification_status,
                 verification_count, success_count, failure_count,
                 created_at, updated_at)
            VALUES 
                (:sid, 'obdb', 'NissanInfiniti', 'Leaf', '79B', '22', '1001', '221001', 
                 'Battery Temp', 'A-40', 'C', 'verified', 0, 0, 0, now(), now())
        """), {'sid': source_id})
        db.session.commit()
        
        # Verify NissanInfiniti resolves to nissan
        assert resolve_maker('NissanInfiniti') == 'nissan'
        
        # Build profiles should include this under 'nissan' (after resolution)
        profiles = build_profiles()
        coverage = get_profile_coverage()
        
        # Should have resolved to nissan
        assert 'nissan' in profiles
        assert 'nissan' in coverage['commands_by_maker']


def test_nfd_common_marker(app):
    """Test that NFD-normalized 공통규격 is properly detected."""
    with app.app_context():
        from app.modules.scanner.wescan_profiles import build_profiles, get_profile_coverage
        import unicodedata
        
        # Create unique identifiers
        unique_id = str(uuid.uuid4())[:8]
        sha_hash = uuid.uuid4().hex + uuid.uuid4().hex[:32]
        file_path = f'/test/nfd_common_{unique_id}.dbc'
        
        # Create definition source
        db.session.execute(text("""
            INSERT INTO definition_sources (source_type, file_path, sha256, file_size, imported_at)
            VALUES ('obdb', :path, :sha, 100, NOW())
        """), {'path': file_path, 'sha': sha_hash})
        db.session.commit()
        
        source_id = db.session.execute(text("""
            SELECT id FROM definition_sources WHERE file_path = :path
        """), {'path': file_path}).scalar()
        
        # Use NFD form (macOS file system behavior)
        maker_nfd = unicodedata.normalize('NFD', '공통규격')
        
        # Create diagnostic command with NFD 공통규격
        db.session.execute(text("""
            INSERT INTO diagnostic_commands 
                (source_id, source_type, maker, model, ecu_address, service, pid, 
                 command_bytes, label, formula, unit, verification_status,
                 verification_count, success_count, failure_count,
                 created_at, updated_at)
            VALUES 
                (:sid, 'obdb', :maker, NULL, '7E0', '01', '05', '0105', 
                 'Coolant Temp', 'A-40', 'C', 'verified', 0, 0, 0, now(), now())
        """), {'sid': source_id, 'maker': maker_nfd})
        db.session.commit()
        
        # Build profiles should recognize NFD form as common
        profiles = build_profiles()
        coverage = get_profile_coverage()
        
        # Should be in _common, not in regular makers
        assert '_common' in profiles
        assert coverage['common_commands'] >= 1
        
        # Should NOT appear in makers list (neither NFC nor NFD form)
        assert '공통규격' not in coverage['commands_by_maker']
        assert maker_nfd not in coverage['commands_by_maker']


def test_nissaninfiniti_with_maker_aliases_db(app):
    """Test NissanInfiniti resolution when maker_aliases table exists in DB."""
    with app.app_context():
        from app.core.makers import resolve_maker
        from app.modules.scanner.wescan_profiles import build_profiles, get_profile_coverage
        
        # Run migration to add NissanInfiniti
        from flask import current_app
        from flask_migrate import upgrade
        upgrade()
        
        # Clear cache to reload from DB
        import app.core.makers as makers_module
        makers_module._ALIASES_CACHE = None
        makers_module._REVERSE_LOOKUP_CACHE = None
        
        # Verify NissanInfiniti resolves to nissan via DB
        assert resolve_maker('NissanInfiniti') == 'nissan'
        
        # Create test data
        unique_id = str(uuid.uuid4())[:8]
        sha_hash = uuid.uuid4().hex + uuid.uuid4().hex[:32]
        file_path = f'/test/nissan_db_{unique_id}.dbc'
        
        db.session.execute(text("""
            INSERT INTO definition_sources (source_type, file_path, sha256, file_size, imported_at)
            VALUES ('obdb', :path, :sha, 100, NOW())
        """), {'path': file_path, 'sha': sha_hash})
        db.session.commit()
        
        source_id = db.session.execute(text("""
            SELECT id FROM definition_sources WHERE file_path = :path
        """), {'path': file_path}).scalar()
        
        db.session.execute(text("""
            INSERT INTO diagnostic_commands 
                (source_id, source_type, maker, model, ecu_address, service, pid, 
                 command_bytes, label, formula, unit, verification_status,
                 verification_count, success_count, failure_count,
                 created_at, updated_at)
            VALUES 
                (:sid, 'obdb', 'NissanInfiniti', 'Leaf', '79B', '22', '1002', '221002', 
                 'SOC', 'A/2', '%', 'verified', 0, 0, 0, now(), now())
        """), {'sid': source_id})
        db.session.commit()
        
        # Build profiles with DB-based maker_aliases
        profiles = build_profiles()
        coverage = get_profile_coverage()
        
        # Should resolve to nissan
        assert 'nissan' in profiles
        assert 'nissan' in coverage['commands_by_maker']
        assert 'NissanInfiniti' not in coverage['commands_by_maker']
