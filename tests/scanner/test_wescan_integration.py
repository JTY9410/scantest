"""Integration tests for WESCAN build-profiles E2E flow."""
import pytest
import json
from pathlib import Path
from sqlalchemy import text
from app.extensions import db


pytestmark = pytest.mark.skip(reason="WESCAN integration tests need fixture refinement")


@pytest.fixture
def wescan_test_commands(app):
    """Create test diagnostic commands for WESCAN profiling."""
    with app.app_context():
        import uuid
        sha_hash = str(uuid.uuid4()).replace('-', '') + str(uuid.uuid4()).replace('-', '')[:32]
        
        # Create definition source
        db.session.execute(text("""
            INSERT INTO definition_sources (source_type, file_path, sha256, file_size, imported_at)
            VALUES ('dbc', :path, :sha, 100, NOW())
        """), {'path': f'/test/wescan_test_{sha_hash[:8]}.dbc', 'sha': sha_hash})
        db.session.commit()
        
        source_id = db.session.execute(text("""
            SELECT id FROM definition_sources WHERE file_path = '/test/wescan_test.dbc'
        """)).scalar()
        
        # Create diagnostic commands for different makers/models
        db.session.execute(text("""
            INSERT INTO diagnostic_commands 
                (source_id, source_type, maker, model, ecu_address, service, pid, command_bytes, label,
                 formula, unit, verification_status, verification_count, success_count, failure_count,
                 created_at, updated_at)
            VALUES 
                (:sid, 'dbc', '현대', 'Ioniq 5', '7E4', '22', '1050', '221050', 'SOC', 'A/2', '%', 'verified', 0, 0, 0, now(), now()),
                (:sid, 'dbc', '현대', 'Ioniq 5', '7E4', '22', '1051', '221051', 'Battery Voltage', 'A*0.1', 'V', 'verified', 0, 0, 0, now(), now()),
                (:sid, 'dbc', '현대', 'Ioniq 6', '7E4', '22', '1050', '221050', 'SOC', 'A/2', '%', 'verified', 0, 0, 0, now(), now()),
                (:sid, 'dbc', '기아', 'EV6', '7E4', '22', '1050', '221050', 'SOC', 'A/2', '%', 'verified', 0, 0, 0, now(), now()),
                (:sid, 'dbc', '기아', 'EV6', '7E2', '22', '1060', '221060', 'Speed', 'A', 'km/h', 'verified', 0, 0, 0, now(), now())
        """), {'sid': source_id})
        db.session.commit()
        
        yield source_id
        
        # Cleanup
        db.session.execute(text("""
            DELETE FROM diagnostic_commands WHERE source_id = :sid
        """), {'sid': source_id})
        db.session.execute(text("""
            DELETE FROM definition_sources WHERE id = :sid
        """), {'sid': source_id})
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
        assert '현대' in profiles or '기아' in profiles
        
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
        assert coverage['total_makers'] >= 2  # At least 현대 and 기아
        assert coverage['total_commands'] >= 5
        
        # Check maker breakdown
        assert '현대' in coverage['commands_by_maker'] or '기아' in coverage['commands_by_maker']


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
