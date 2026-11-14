"""Integration tests for reimport-canze-names CLI command."""
import json
import pytest
from pathlib import Path
from sqlalchemy import text
from app.extensions import db


@pytest.fixture
def canze_test_data(app, tmp_path):
    """Create test CanZE CSV file and DB records."""
    with app.app_context():
        # Create test CSV file
        csv_file = tmp_path / "test_canze.csv"
        csv_content = """sid,ID,startBit,endBit,resolution,offset,decimals,unit,requestId,responseId,options,FieldName
1,7E4,0,7,1,0,0,V,2101,6101,ff,Battery Voltage
2,7E4,8,15,0.1,0,1,A,2102,6102,4ff,Battery Current
3,7E4,16,23,1,-40,0,C,2103,6103,option1,Battery Temperature
"""
        csv_file.write_text(csv_content)
        
        # Create definition source
        sha_hash = '0' * 64
        db.session.execute(text("""
            INSERT INTO definition_sources (source_type, file_path, maker, parser_version, sha256, file_size, imported_at, created_at)
            VALUES ('canze', :path, 'TestMaker', '1.0', :sha, 100, now(), now())
        """), {'path': str(csv_file), 'sha': sha_hash})
        db.session.commit()
        
        source_id = db.session.execute(text("""
            SELECT id FROM definition_sources WHERE file_path = :path
        """), {'path': str(csv_file)}).scalar()
        
        # Create diagnostic commands with WRONG labels (from row[10], the 'options' column)
        db.session.execute(text("""
            INSERT INTO diagnostic_commands 
                (source_id, source_type, service, pid, command_bytes, label, created_at, updated_at)
            VALUES 
                (:sid, 'canze', '21', '01', '2101', 'ff', now(), now()),
                (:sid, 'canze', '21', '02', '2102', '4ff', now(), now()),
                (:sid, 'canze', '21', '03', '2103', 'option1', now(), now())
        """), {'sid': source_id})
        db.session.commit()
        
        return {
            'csv_file': csv_file,
            'source_id': source_id
        }


def test_reimport_canze_names_report_only(app, canze_test_data):
    """Test --report-only shows changes without applying them."""
    with app.app_context():
        runner = app.test_cli_runner()
        result = runner.invoke(args=['definitions', 'reimport-canze-names', '--report-only'])
        
        assert result.exit_code == 0
        assert 'SUMMARY: 3 changes found' in result.output
        assert '2101' in result.output
        assert 'ff' in result.output
        assert 'Battery Voltage' in result.output
        assert '(Use --yes to apply these changes)' in result.output
        
        # Verify no changes were made
        labels = db.session.execute(text("""
            SELECT label FROM diagnostic_commands WHERE command_bytes IN ('2101', '2102', '2103')
            ORDER BY command_bytes
        """)).fetchall()
        
        assert labels[0][0] == 'ff'  # Still old value
        assert labels[1][0] == '4ff'
        assert labels[2][0] == 'option1'


def test_reimport_canze_names_yes(app, canze_test_data):
    """Test --yes applies changes and creates revert file."""
    with app.app_context():
        runner = app.test_cli_runner()
        result = runner.invoke(args=['definitions', 'reimport-canze-names', '--yes'])
        
        assert result.exit_code == 0
        assert 'Updated 3 command names' in result.output
        assert 'Revert data saved' in result.output
        
        # Verify changes were applied
        labels = db.session.execute(text("""
            SELECT command_bytes, label FROM diagnostic_commands 
            WHERE command_bytes IN ('2101', '2102', '2103')
            ORDER BY command_bytes
        """)).fetchall()
        
        assert labels[0][1] == 'Battery Voltage'  # Corrected from row[11]
        assert labels[1][1] == 'Battery Current'
        assert labels[2][1] == 'Battery Temperature'
        
        # Verify revert file was created
        revert_file = Path("/tmp/canze_label_revert.json")
        assert revert_file.exists()
        
        with open(revert_file, 'r') as f:
            revert_data = json.load(f)
        
        assert len(revert_data) == 3
        assert revert_data[0]['old_label'] == 'ff'
        assert revert_data[0]['new_label'] == 'Battery Voltage'


def test_reimport_canze_names_revert(app, canze_test_data):
    """Test --revert restores previous labels."""
    with app.app_context():
        runner = app.test_cli_runner()
        
        # First apply changes
        result = runner.invoke(args=['definitions', 'reimport-canze-names', '--yes'])
        assert result.exit_code == 0
        
        # Verify changes were applied
        label = db.session.execute(text("""
            SELECT label FROM diagnostic_commands WHERE command_bytes = '2101'
        """)).scalar()
        assert label == 'Battery Voltage'
        
        # Now revert
        result = runner.invoke(args=['definitions', 'reimport-canze-names', '--revert'], input='y\n')
        assert result.exit_code == 0
        assert 'Reverted 3 label changes' in result.output
        
        # Verify labels were restored
        labels = db.session.execute(text("""
            SELECT command_bytes, label FROM diagnostic_commands 
            WHERE command_bytes IN ('2101', '2102', '2103')
            ORDER BY command_bytes
        """)).fetchall()
        
        assert labels[0][1] == 'ff'  # Back to original
        assert labels[1][1] == '4ff'
        assert labels[2][1] == 'option1'
        
        # Verify revert file was deleted
        revert_file = Path("/tmp/canze_label_revert.json")
        assert not revert_file.exists()


def test_reimport_canze_names_revert_without_prior_run(app):
    """Test --revert fails gracefully when no revert data exists."""
    with app.app_context():
        # Remove any existing revert file
        revert_file = Path("/tmp/canze_label_revert.json")
        if revert_file.exists():
            revert_file.unlink()
        
        runner = app.test_cli_runner()
        result = runner.invoke(args=['definitions', 'reimport-canze-names', '--revert'])
        
        assert result.exit_code == 0
        assert 'No revert data found' in result.output


def test_reimport_canze_names_no_changes_needed(app, canze_test_data):
    """Test when labels are already correct."""
    with app.app_context():
        # First apply changes to make labels correct
        runner = app.test_cli_runner()
        runner.invoke(args=['definitions', 'reimport-canze-names', '--yes'])
        
        # Try again - should report no changes
        result = runner.invoke(args=['definitions', 'reimport-canze-names', '--report-only'])
        
        assert result.exit_code == 0
        assert 'SUMMARY: 0 changes found' in result.output
