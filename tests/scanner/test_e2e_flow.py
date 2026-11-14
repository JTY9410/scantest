"""End-to-end flow test: OBD2 → diagnostic_commands DB → WESCAN profiles.

Tests the complete flow from command definitions to profile generation,
verifying that DTC and BMS commands are properly included.
"""
import pytest
import uuid
from sqlalchemy import text
from app.extensions import db


@pytest.fixture
def e2e_test_data(app):
    """Create comprehensive test data covering OBD2, DTC, and BMS commands."""
    with app.app_context():
        # Generate unique identifiers for this test run
        unique_id = str(uuid.uuid4())[:8]
        sha_hash = uuid.uuid4().hex + uuid.uuid4().hex[:32]
        file_path = f'/test/e2e_flow_{unique_id}.dbc'
        
        # Create definition source
        db.session.execute(text("""
            INSERT INTO definition_sources (source_type, file_path, sha256, file_size, imported_at)
            VALUES ('canze', :path, :sha, 100, NOW())
        """), {'path': file_path, 'sha': sha_hash})
        db.session.commit()
        
        source_id = db.session.execute(text("""
            SELECT id FROM definition_sources WHERE file_path = :path
        """), {'path': file_path}).scalar()
        
        # Insert comprehensive test commands
        db.session.execute(text("""
            INSERT INTO diagnostic_commands 
                (source_id, source_type, maker, model, ecu_address, service, pid, command_bytes, 
                 label, formula, unit, verification_status, verification_count, success_count, failure_count,
                 created_at, updated_at)
            VALUES 
                -- OBD2 Standard (Mode 01)
                (:sid, 'canze', 'renault', 'ZOE', '7DF', '01', '00', '0100', 
                 'PIDs Supported', 'A', '', 'verified', 0, 0, 0, now(), now()),
                (:sid, 'canze', 'renault', 'ZOE', '7DF', '01', '0C', '010C', 
                 'Engine RPM', 'A*256+B/4', 'rpm', 'verified', 0, 0, 0, now(), now()),
                
                -- DTC Commands (Mode 03, 07, 0A)
                (:sid, 'canze', 'renault', 'ZOE', '7E4', '03', '', '03', 
                 'Request DTC', '', '', 'verified', 0, 0, 0, now(), now()),
                (:sid, 'canze', 'renault', 'ZOE', '7E4', '07', '', '07', 
                 'Request Pending DTC', '', '', 'verified', 0, 0, 0, now(), now()),
                (:sid, 'canze', 'renault', 'ZOE', '7E4', '0A', '', '0A', 
                 'Request Permanent DTC', '', '', 'verified', 0, 0, 0, now(), now()),
                
                -- BMS Commands (Mode 22)
                (:sid, 'canze', 'renault', 'ZOE', '7BB', '22', '2002', '222002', 
                 'Battery SOC', 'A/2', '%', 'verified', 0, 0, 0, now(), now()),
                (:sid, 'canze', 'renault', 'ZOE', '7BB', '22', '2003', '222003', 
                 'Battery Voltage', 'A*256+B/10', 'V', 'verified', 0, 0, 0, now(), now()),
                (:sid, 'canze', 'renault', 'ZOE', '7BB', '22', '2004', '222004', 
                 'Battery Current', '(A*256+B-32768)/10', 'A', 'verified', 0, 0, 0, now(), now()),
                
                -- Additional ECUs
                (:sid, 'canze', 'renault', 'ZOE', '7E2', '22', '1001', '221001', 
                 'Motor Speed', 'A*256+B', 'rpm', 'verified', 0, 0, 0, now(), now())
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


def test_e2e_obd2_to_wescan_profile(app, e2e_test_data):
    """Test complete flow: OBD2 commands → DB → WESCAN profile generation."""
    with app.app_context():
        from app.modules.scanner.wescan_profiles import build_profiles, get_profile_coverage
        
        # Build WESCAN profiles from DB
        profiles = build_profiles()
        coverage = get_profile_coverage()
        
        # Verify renault maker is present
        assert 'renault' in profiles, "Renault maker should be in profiles"
        
        # Verify ZOE model is present
        assert 'ZOE' in profiles['renault'], "ZOE model should be in profiles"
        
        # Verify ECUs are present
        ecus = profiles['renault']['ZOE']
        assert '7DF' in ecus, "OBD2 ECU 7DF should be present"
        assert '7E4' in ecus, "BMS ECU 7E4 should be present"
        assert '7BB' in ecus, "Battery ECU 7BB should be present"
        assert '7E2' in ecus, "Motor ECU 7E2 should be present"
        
        # Verify OBD2 commands are included
        obd2_commands = ecus['7DF']
        assert '01_00' in obd2_commands, "PID 0100 should be included"
        assert '01_0C' in obd2_commands, "PID 010C (RPM) should be included"
        
        # Verify DTC commands are included
        dtc_commands = ecus['7E4']
        assert '03_' in dtc_commands, "DTC request (03) should be included"
        assert '07_' in dtc_commands, "Pending DTC (07) should be included"
        assert '0A_' in dtc_commands, "Permanent DTC (0A) should be included"
        
        # Verify BMS commands are included
        bms_commands = ecus['7BB']
        assert '22_2002' in bms_commands, "Battery SOC should be included"
        assert '22_2003' in bms_commands, "Battery Voltage should be included"
        assert '22_2004' in bms_commands, "Battery Current should be included"
        
        # Verify coverage statistics
        assert coverage['total_commands'] >= 9, "Should have at least 9 test commands"
        assert 'renault' in coverage['commands_by_maker'], "Renault should be in coverage"
        assert coverage['commands_by_maker']['renault'] >= 9, "Renault should have at least 9 commands"


def test_e2e_profile_export_format(app, e2e_test_data, tmp_path):
    """Test that exported WESCAN profiles have correct format with all command types."""
    with app.app_context():
        from app.modules.scanner.wescan_profiles import build_profiles
        import json
        
        # Build and export profiles
        profiles = build_profiles()
        export_file = tmp_path / "wescan_e2e_test.json"
        
        with open(export_file, 'w') as f:
            json.dump(profiles, f, indent=2, ensure_ascii=False)
        
        # Verify export file exists and is valid JSON
        assert export_file.exists()
        
        with open(export_file, 'r') as f:
            exported = json.load(f)
        
        # Verify structure
        assert 'renault' in exported
        assert 'ZOE' in exported['renault']
        
        # Verify command details are complete
        bms_soc = exported['renault']['ZOE']['7BB']['22_2002']
        assert 'label' in bms_soc
        assert 'formula' in bms_soc
        assert 'unit' in bms_soc
        assert bms_soc['label'] == 'Battery SOC'
        assert bms_soc['unit'] == '%'
        
        # Verify DTC command format (no formula/unit for DTC requests)
        dtc_cmd = exported['renault']['ZOE']['7E4']['03_']
        assert 'label' in dtc_cmd
        assert dtc_cmd['label'] == 'Request DTC'


def test_e2e_cli_build_profiles_execution(app, e2e_test_data):
    """Test WESCAN CLI command executes successfully with real data."""
    with app.app_context():
        runner = app.test_cli_runner()
        result = runner.invoke(args=['wescan', 'build-profiles'])
        
        # Verify CLI execution success
        assert result.exit_code == 0, f"CLI failed with: {result.output}"
        
        # Verify output contains expected information
        assert 'WESCAN COMMAND PROFILES' in result.output
        assert 'Building profiles from diagnostic_commands' in result.output
        assert 'Coverage Statistics' in result.output
        assert 'Total makers with profiles:' in result.output
        
        # Verify renault is mentioned
        assert 'renault' in result.output.lower()


def test_e2e_profile_coverage_by_service(app, e2e_test_data):
    """Test that profile coverage provides correct statistics."""
    with app.app_context():
        from app.modules.scanner.wescan_profiles import get_profile_coverage
        
        coverage = get_profile_coverage()
        
        # Verify basic coverage stats
        assert 'total_commands' in coverage
        assert coverage['total_commands'] >= 9  # Our test data has 9 commands
        
        # Verify maker breakdown
        assert 'commands_by_maker' in coverage
        assert 'renault' in coverage['commands_by_maker']
        assert coverage['commands_by_maker']['renault'] >= 9
        
        # Verify ECU breakdown
        assert 'commands_by_ecu' in coverage
        ecus = coverage['commands_by_ecu']
        assert '7DF' in ecus  # OBD2
        assert '7E4' in ecus  # DTC
        assert '7BB' in ecus  # BMS
        assert '7E2' in ecus  # Motor


def test_e2e_null_ecu_handling(app):
    """Test that commands with NULL ecu_address are handled correctly."""
    with app.app_context():
        unique_id = str(uuid.uuid4())[:8]
        sha_hash = uuid.uuid4().hex + uuid.uuid4().hex[:32]
        file_path = f'/test/null_ecu_{unique_id}.dbc'
        
        db.session.execute(text("""
            INSERT INTO definition_sources (source_type, file_path, sha256, file_size, imported_at)
            VALUES ('wican', :path, :sha, 100, NOW())
        """), {'path': file_path, 'sha': sha_hash})
        db.session.commit()
        
        source_id = db.session.execute(text("""
            SELECT id FROM definition_sources WHERE file_path = :path
        """), {'path': file_path}).scalar()
        
        # Insert command with NULL ecu_address
        db.session.execute(text("""
            INSERT INTO diagnostic_commands 
                (source_id, source_type, maker, model, ecu_address, service, pid, command_bytes, 
                 label, verification_status, verification_count, success_count, failure_count,
                 created_at, updated_at)
            VALUES 
                (:sid, 'wican', 'tesla', 'Model 3', NULL, '01', '00', '0100', 
                 'PIDs Supported', 'verified', 0, 0, 0, now(), now())
        """), {'sid': source_id})
        db.session.commit()
        
        from app.modules.scanner.wescan_profiles import build_profiles
        
        # Should not crash with NULL ecu_address
        profiles = build_profiles()
        
        # Verify tesla is in profiles
        assert 'tesla' in profiles
        assert 'Model 3' in profiles['tesla']
        
        # NULL ecu should be grouped as 'unknown'
        assert 'unknown' in profiles['tesla']['Model 3']
        assert '01_00' in profiles['tesla']['Model 3']['unknown']
        
        # Cleanup
        db.session.execute(text("DELETE FROM diagnostic_commands WHERE source_id = :sid"), {'sid': source_id})
        db.session.execute(text("DELETE FROM definition_sources WHERE file_path = :path"), {'path': file_path})
        db.session.commit()
