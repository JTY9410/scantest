"""Real-data integration tests for reimport-canze-names CLI command."""
import pytest
from pathlib import Path
from sqlalchemy import text
from app.extensions import db


@pytest.fixture
def canze_multifield_data(app, tmp_path):
    """Create realistic CanZE CSV with multiple fields per command."""
    with app.app_context():
        # Create test CSV file with SAME command (19020F) for multiple fields
        csv_file = tmp_path / "test_canze_multifield.csv"
        csv_content = """sid,ID,startBit,endBit,resolution,offset,decimals,unit,requestId,responseId,options,FieldName
100,7DF,16,17,1,0,0,,19020F,5902,ff,DTCStatus.testFailed
101,7DF,18,19,1,0,0,,19020F,5902,2ff,DTCStatus.testFailedThisOperationCycle
102,7DF,20,21,1,0,0,,19020F,5902,4ff,DTCStatus.pendingDTC
103,7DF,24,31,1,0,0,,19020F,5902,1ff,DTC.Byte0
104,7E4,0,7,0.1,0,1,V,2101,6101,ff,Battery.Voltage
105,7E4,8,15,0.1,0,1,A,2101,6101,4ff,Battery.Current
"""
        csv_file.write_text(csv_content)
        
        # Create definition source
        sha_hash = '0' * 64
        db.session.execute(text("""
            INSERT INTO definition_sources (source_type, file_path, sha256, file_size, imported_at)
            VALUES ('canze', :path, :sha, 100, now())
        """), {'path': str(csv_file), 'sha': sha_hash})
        db.session.commit()
        
        source_id = db.session.execute(text("""
            SELECT id FROM definition_sources WHERE file_path = :path
        """), {'path': str(csv_file)}).scalar()
        
        # Create diagnostic commands with WRONG labels (from row[10], options column)
        # Same command 19020F but different bit positions -> different fields
        db.session.execute(text("""
            INSERT INTO diagnostic_commands 
                (source_id, source_type, ecu_address, service, pid, command_bytes, label,
                 response_start_byte, response_bit_offset, verification_status, created_at, updated_at)
            VALUES 
                (:sid, 'canze', '7DF', '19', '020F', '19020F', 'ff', 2, 0, 'needs_verification', now(), now()),
                (:sid, 'canze', '7DF', '19', '020F', '19020F', '2ff', 2, 2, 'needs_verification', now(), now()),
                (:sid, 'canze', '7DF', '19', '020F', '19020F', '4ff', 2, 4, 'needs_verification', now(), now()),
                (:sid, 'canze', '7DF', '19', '020F', '19020F', '1ff', 3, 0, 'needs_verification', now(), now()),
                (:sid, 'canze', '7E4', '21', '01', '2101', 'ff', 0, 0, 'needs_verification', now(), now()),
                (:sid, 'canze', '7E4', '21', '01', '2101', '4ff', 1, 0, 'needs_verification', now(), now())
        """), {'sid': source_id})
        db.session.commit()
        
        return {
            'csv_file': csv_file,
            'source_id': source_id
        }


def test_reimport_canze_names_multifield_report(app, canze_multifield_data):
    """Test that report-only shows all 6 distinct field changes."""
    with app.app_context():
        runner = app.test_cli_runner()
        result = runner.invoke(args=['definitions', 'reimport-canze-names', '--report-only'])
        
        assert result.exit_code == 0
        assert 'SUMMARY: 6 changes' in result.output
        
        # Check specific fields are mentioned
        assert 'DTCStatus.testFailed' in result.output
        assert 'Battery.Voltage' in result.output
        
        # Verify no changes were made
        labels = db.session.execute(text("""
            SELECT label FROM diagnostic_commands 
            WHERE command_bytes = '19020F'
            ORDER BY response_start_byte, response_bit_offset
        """)).fetchall()
        
        assert len(labels) == 4
        assert labels[0][0] == 'ff'  # Still old value


def test_reimport_canze_names_multifield_apply(app, canze_multifield_data):
    """Test that --yes correctly updates each field separately."""
    with app.app_context():
        runner = app.test_cli_runner()
        result = runner.invoke(args=['definitions', 'reimport-canze-names', '--yes'])
        
        assert result.exit_code == 0
        assert 'Updated 6 command names' in result.output
        assert 'Revert data saved to label_change_history' in result.output
        
        # Verify each field got its CORRECT name (not overwritten)
        fields = db.session.execute(text("""
            SELECT command_bytes, response_start_byte, response_bit_offset, label
            FROM diagnostic_commands 
            WHERE command_bytes IN ('19020F', '2101')
            ORDER BY command_bytes, response_start_byte, response_bit_offset
        """)).fetchall()
        
        assert len(fields) == 6
        
        # 19020F fields
        assert fields[0] == ('19020F', 2, 0, 'DTCStatus.testFailed')
        assert fields[1] == ('19020F', 2, 2, 'DTCStatus.testFailedThisOperationCycle')
        assert fields[2] == ('19020F', 2, 4, 'DTCStatus.pendingDTC')
        assert fields[3] == ('19020F', 3, 0, 'DTC.Byte0')
        
        # 2101 fields
        assert fields[4] == ('2101', 0, 0, 'Battery.Voltage')
        assert fields[5] == ('2101', 1, 0, 'Battery.Current')
        
        # Verify history was saved
        history_count = db.session.execute(text("""
            SELECT COUNT(*) FROM label_change_history
            WHERE operation = 'canze_reimport' AND reverted_at IS NULL
        """)).scalar()
        
        assert history_count == 6


def test_reimport_canze_names_idempotent(app, canze_multifield_data):
    """Test that running --yes twice results in 0 changes on second run."""
    with app.app_context():
        runner = app.test_cli_runner()
        
        # First run
        result1 = runner.invoke(args=['definitions', 'reimport-canze-names', '--yes'])
        assert result1.exit_code == 0
        assert 'Updated 6 command names' in result1.output
        
        # Second run - should find 0 changes
        result2 = runner.invoke(args=['definitions', 'reimport-canze-names', '--report-only'])
        assert result2.exit_code == 0
        assert 'SUMMARY: 0 changes' in result2.output
        
        # Try --yes again
        result3 = runner.invoke(args=['definitions', 'reimport-canze-names', '--yes'])
        assert result3.exit_code == 0
        assert 'No changes needed' in result3.output


def test_reimport_canze_names_revert(app, canze_multifield_data):
    """Test that --revert --yes restores all original labels."""
    with app.app_context():
        runner = app.test_cli_runner()
        
        # Apply changes
        result = runner.invoke(args=['definitions', 'reimport-canze-names', '--yes'])
        assert result.exit_code == 0
        
        # Verify changes were applied
        label = db.session.execute(text("""
            SELECT label FROM diagnostic_commands 
            WHERE command_bytes = '19020F' AND response_start_byte = 2 AND response_bit_offset = 0
        """)).scalar()
        assert label == 'DTCStatus.testFailed'
        
        # Revert
        result = runner.invoke(args=['definitions', 'reimport-canze-names', '--revert', '--yes'])
        assert result.exit_code == 0
        assert 'Reverted 6 label changes' in result.output
        
        # Verify all labels were restored
        labels = db.session.execute(text("""
            SELECT label FROM diagnostic_commands 
            WHERE command_bytes IN ('19020F', '2101')
            ORDER BY command_bytes, response_start_byte, response_bit_offset
        """)).fetchall()
        
        # Should be back to hex values
        assert labels[0][0] == 'ff'
        assert labels[1][0] == '2ff'
        assert labels[2][0] == '4ff'
        assert labels[3][0] == '1ff'
        assert labels[4][0] == 'ff'
        assert labels[5][0] == '4ff'
        
        # Verify history was marked as reverted
        reverted_count = db.session.execute(text("""
            SELECT COUNT(*) FROM label_change_history
            WHERE operation = 'canze_reimport' AND reverted_at IS NOT NULL
        """)).scalar()
        
        assert reverted_count == 6


def test_reimport_canze_names_no_double_revert(app, canze_multifield_data):
    """Test that running --revert twice doesn't double-revert."""
    with app.app_context():
        runner = app.test_cli_runner()
        
        # Apply and revert
        runner.invoke(args=['definitions', 'reimport-canze-names', '--yes'])
        result1 = runner.invoke(args=['definitions', 'reimport-canze-names', '--revert', '--yes'])
        assert result1.exit_code == 0
        assert 'Reverted 6 label changes' in result1.output
        
        # Try to revert again - should find nothing
        result2 = runner.invoke(args=['definitions', 'reimport-canze-names', '--revert', '--yes'])
        assert result2.exit_code == 0
        assert 'No revert data found' in result2.output
