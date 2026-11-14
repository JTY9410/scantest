"""Integration tests for backfill-ecu command against actual migration schema.

Tests all three modes:
1. --report-only (dry run with projections)
2. --yes (apply backfill)
3. --revert --yes (undo backfill)
"""
import pytest
from sqlalchemy import text
from app.extensions import db
from app.modules.definitions.models import DiagnosticCommand, DbcSignal, DbcMessage, DefinitionSource


@pytest.fixture
def backfill_data(app):
    """Create test data with actual schema relationships."""
    with app.app_context():
        # Create a definition source
        source = DefinitionSource(
            file_path="/test/definitions/BMS_diagnostics.dbc",
            sha256="a" * 64,  # Valid SHA256 hash
            file_size=1024,
            source_type="dbc"
        )
        db.session.add(source)
        db.session.flush()
        
        # Create DBC message with BMS transmitter
        message = DbcMessage(
            source_id=source.id,
            can_id=0x7E4,
            message_name="BMS_Status",
            dlc=8,
            sender="BMS"  # This is the BO_ transmitter
        )
        db.session.add(message)
        db.session.flush()
        
        # Create DBC signals linked to message
        signal1 = DbcSignal(
            message_id=message.id,
            signal_name="BatterySOC",
            start_bit=0,
            bit_length=8,
            byte_order="little",
            value_type="unsigned",
            factor=1.0,
            offset=0.0,
            unit="%",
            comment="State of charge",
            ecu_module=None  # Will be backfilled
        )
        
        signal2 = DbcSignal(
            message_id=message.id,
            signal_name="BatteryVoltage",
            start_bit=8,
            bit_length=16,
            byte_order="little",
            value_type="unsigned",
            factor=0.1,
            offset=0.0,
            unit="V",
            comment="Battery pack voltage",
            ecu_module=None
        )
        
        db.session.add_all([signal1, signal2])
        
        # Create diagnostic command with BMS in file path
        command = DiagnosticCommand(
            source_id=source.id,
            source_type="obdb",
            service="22",
            pid="0101",
            command_bytes="220101",
            label="BMS Voltage",
            notes="Read BMS battery voltage",
            ecu_module=None  # Will be backfilled
        )
        db.session.add(command)
        
        db.session.commit()
        
        yield {
            'source_id': source.id,
            'message_id': message.id,
            'signal1_id': signal1.id,
            'signal2_id': signal2.id,
            'command_id': command.id
        }
        
        # Cleanup
        db.session.rollback()


def test_backfill_ecu_report_only_mode(app, backfill_data):
    """Test --report-only shows projections without making changes."""
    runner = app.test_cli_runner()
    
    with app.app_context():
        # Check BEFORE state
        signal1 = db.session.get(DbcSignal, backfill_data['signal1_id'])
        command = db.session.get(DiagnosticCommand, backfill_data['command_id'])
        
        assert signal1.ecu_module is None
        assert command.ecu_module is None
        
        # Run --report-only
        result = runner.invoke(args=['definitions', 'backfill-ecu', '--report-only'])
        
        # Should succeed
        assert result.exit_code == 0, f"Command failed: {result.output}"
        
        # Should show projections
        assert "PROJECTED After Backfill" in result.output
        assert "Per-Rule Hit Counts" in result.output
        
        # Check data is UNCHANGED
        db.session.expire_all()
        signal1 = db.session.get(DbcSignal, backfill_data['signal1_id'])
        command = db.session.get(DiagnosticCommand, backfill_data['command_id'])
        
        assert signal1.ecu_module is None, "--report-only should not modify data"
        assert command.ecu_module is None, "--report-only should not modify data"
        assert signal1.ecu_backfill_evidence is None
        assert command.ecu_backfill_evidence is None


def test_backfill_ecu_apply_mode(app, backfill_data):
    """Test --yes applies backfill and stores evidence."""
    runner = app.test_cli_runner()
    
    with app.app_context():
        # Check BEFORE state
        signal1 = db.session.get(DbcSignal, backfill_data['signal1_id'])
        signal2 = db.session.get(DbcSignal, backfill_data['signal2_id'])
        command = db.session.get(DiagnosticCommand, backfill_data['command_id'])
        
        assert signal1.ecu_module is None
        assert signal2.ecu_module is None
        assert command.ecu_module is None
        
        # Run --yes
        result = runner.invoke(args=['definitions', 'backfill-ecu', '--yes'])
        
        # Should succeed
        assert result.exit_code == 0, f"Command failed: {result.output}"
        assert "Applying backfill" in result.output
        assert "Backfill complete" in result.output
        
        # Check data is CHANGED
        db.session.expire_all()
        signal1 = db.session.get(DbcSignal, backfill_data['signal1_id'])
        signal2 = db.session.get(DbcSignal, backfill_data['signal2_id'])
        command = db.session.get(DiagnosticCommand, backfill_data['command_id'])
        
        # Signals should have BMS from transmitter
        assert signal1.ecu_module == 'BMS', "Should backfill from DBC transmitter"
        assert signal2.ecu_module == 'BMS'
        assert signal1.ecu_backfill_evidence is not None, "Should store evidence"
        assert signal2.ecu_backfill_evidence is not None
        
        # Command should have BMS from file path
        assert command.ecu_module == 'BMS', "Should backfill from file path"
        assert command.ecu_backfill_evidence is not None, "Should store evidence"
        
        # Evidence should be a dict with rule and matched_text (JSON column auto-deserializes)
        sig_evidence = signal1.ecu_backfill_evidence
        assert isinstance(sig_evidence, dict)
        assert 'rule' in sig_evidence
        assert 'matched_text' in sig_evidence
        assert sig_evidence['rule'] == 'dbc_transmitter'
        
        cmd_evidence = command.ecu_backfill_evidence
        assert isinstance(cmd_evidence, dict)
        assert 'rule' in cmd_evidence
        assert 'matched_text' in cmd_evidence
        # Rule can be either 'file_path' or 'uds_can_id' depending on extraction order
        assert cmd_evidence['rule'] in ('file_path', 'uds_can_id')


def test_backfill_ecu_revert_mode(app, backfill_data):
    """Test --revert --yes undoes backfill using evidence."""
    runner = app.test_cli_runner()
    
    with app.app_context():
        # First apply backfill
        result = runner.invoke(args=['definitions', 'backfill-ecu', '--yes'])
        assert result.exit_code == 0
        
        # Verify it was applied
        db.session.expire_all()
        signal1 = db.session.get(DbcSignal, backfill_data['signal1_id'])
        command = db.session.get(DiagnosticCommand, backfill_data['command_id'])
        
        assert signal1.ecu_module == 'BMS'
        assert command.ecu_module == 'BMS'
        assert signal1.ecu_backfill_evidence is not None
        assert command.ecu_backfill_evidence is not None
        
        # Now revert
        result = runner.invoke(args=['definitions', 'backfill-ecu', '--revert', '--yes'])
        
        # Should succeed
        assert result.exit_code == 0, f"Revert failed: {result.output}"
        assert "REVERTING ECU/CATEGORY BACKFILL" in result.output
        assert "Reverted:" in result.output
        
        # Check data is REVERTED
        db.session.expire_all()
        signal1 = db.session.get(DbcSignal, backfill_data['signal1_id'])
        command = db.session.get(DiagnosticCommand, backfill_data['command_id'])
        
        assert signal1.ecu_module is None, "Should revert to NULL"
        assert command.ecu_module is None, "Should revert to NULL"
        assert signal1.ecu_backfill_evidence is None, "Should clear evidence"
        assert command.ecu_backfill_evidence is None, "Should clear evidence"


def test_backfill_ecu_handles_complex_joins(app):
    """Test that complex joins work correctly (signals → messages → sources)."""
    runner = app.test_cli_runner()
    
    with app.app_context():
        # Create data with multiple sources and messages
        source1 = DefinitionSource(
            file_path="/vehicle/hyundai/ioniq5/MCU_controls.dbc",
            sha256="b" * 64,
            file_size=2048,
            source_type="dbc"
        )
        source2 = DefinitionSource(
            file_path="/vehicle/kia/ev6/OBC_charging.dbc",
            sha256="c" * 64,
            file_size=3072,
            source_type="dbc"
        )
        db.session.add_all([source1, source2])
        db.session.flush()
        
        # Message 1: MCU transmitter
        msg1 = DbcMessage(
            source_id=source1.id,
            can_id=0x100,
            message_name="MCU_Data",
            dlc=8,
            sender="MCU"
        )
        
        # Message 2: OBC transmitter
        msg2 = DbcMessage(
            source_id=source2.id,
            can_id=0x200,
            message_name="OBC_Status",
            dlc=8,
            sender="OBC"
        )
        
        db.session.add_all([msg1, msg2])
        db.session.flush()
        
        # Signals linked to different messages/sources
        sig1 = DbcSignal(
            message_id=msg1.id,
            signal_name="MotorRPM",
            start_bit=0,
            bit_length=16,
            byte_order="little",
            value_type="unsigned"
        )
        
        sig2 = DbcSignal(
            message_id=msg2.id,
            signal_name="ChargingCurrent",
            start_bit=0,
            bit_length=16,
            byte_order="little",
            value_type="unsigned"
        )
        
        db.session.add_all([sig1, sig2])
        db.session.commit()
        
        sig1_id = sig1.id
        sig2_id = sig2.id
        
        # Run backfill
        result = runner.invoke(args=['definitions', 'backfill-ecu', '--yes'])
        assert result.exit_code == 0
        
        # Verify correct ECUs assigned through proper joins
        db.session.expire_all()
        sig1 = db.session.get(DbcSignal, sig1_id)
        sig2 = db.session.get(DbcSignal, sig2_id)
        
        assert sig1.ecu_module == 'MCU', "Should get ECU from message1 transmitter"
        assert sig2.ecu_module == 'OBC', "Should get ECU from message2 transmitter"


def test_backfill_ecu_no_false_matches(app):
    """Test that backfill doesn't make false matches from signal names."""
    runner = app.test_cli_runner()
    
    with app.app_context():
        # Create source without ECU indicators
        source = DefinitionSource(
            file_path="/generic/obd2_standard.dbc",
            sha256="d" * 64,
            file_size=512,
            source_type="dbc"
        )
        db.session.add(source)
        db.session.flush()
        
        # Message with no specific transmitter
        msg = DbcMessage(
            source_id=source.id,
            can_id=0x7DF,
            message_name="OBD2_Request",
            dlc=8,
            sender=None  # No transmitter
        )
        db.session.add(msg)
        db.session.flush()
        
        # Signal with ECU-like name but should NOT match
        sig = DbcSignal(
            message_id=msg.id,
            signal_name="BMS_SOC_Estimate",  # Has 'BMS' in name but shouldn't match
            start_bit=0,
            bit_length=8,
            byte_order="little",
            value_type="unsigned",
            comment="Generic OBD SOC reading"
        )
        db.session.add(sig)
        db.session.commit()
        
        sig_id = sig.id
        
        # Run backfill
        result = runner.invoke(args=['definitions', 'backfill-ecu', '--yes'])
        assert result.exit_code == 0
        
        # Should NOT backfill (no evidence from transmitter or file path)
        db.session.expire_all()
        sig = db.session.get(DbcSignal, sig_id)
        
        assert sig.ecu_module is None, "Should not guess ECU from signal name"
        assert sig.ecu_backfill_evidence is None
