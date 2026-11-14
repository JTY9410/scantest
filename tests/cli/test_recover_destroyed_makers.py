"""Integration tests for recover-destroyed-makers CLI command."""
import pytest
from sqlalchemy import text
from app.extensions import db


@pytest.fixture
def destroyed_makers_data(app):
    """Create test data with truncated maker names."""
    with app.app_context():
        # Create test sources with file paths indicating full maker names
        sha_hash = '0' * 64
        db.session.execute(text("""
            INSERT INTO definition_sources (id, source_type, file_path, sha256, file_size, imported_at)
            VALUES 
                (1001, 'dbc', '/data/dbc/Aston_Martin_DB11.dbc', :sha, 100, NOW()),
                (1002, 'dbc', '/data/dbc/MV_Agusta_F4.dbc', :sha, 100, NOW()),
                (1003, 'dbc', '/data/dbc/Legend_Cars_34.dbc', :sha, 100, NOW()),
                (1004, 'dbc', '/data/dbc/SCCA_Enterprises_Formula.dbc', :sha, 100, NOW()),
                (1005, 'dbc', '/data/dbc/BT1_Chevy.dbc', :sha, 100, NOW()),
                (1006, 'dbc', '/data/dbc/공통규격.dbc', :sha, 100, NOW())
        """), {'sha': sha_hash})
        
        # Create vehicle definitions with truncated makers
        db.session.execute(text("""
            INSERT INTO vehicle_definitions (source_id, maker, model, powertrain, created_at)
            VALUES 
                (1001, 'Aston', 'DB11', 'ice', NOW()),
                (1002, 'MV', 'F4', 'ice', NOW()),
                (1003, 'Legend', '34', 'ice', NOW()),
                (1004, 'SCCA', 'Formula', 'ice', NOW()),
                (1005, 'BT1', 'Chevy', 'ice', NOW()),
                (1006, '공통규격', 'Common', 'unknown', NOW())
        """))
        db.session.commit()
        
        yield
        
        # Cleanup
        db.session.execute(text("DELETE FROM vehicle_definitions WHERE source_id >= 1001"))
        db.session.execute(text("DELETE FROM definition_sources WHERE id >= 1001"))
        db.session.commit()


def test_recover_destroyed_makers_report_only(app, destroyed_makers_data):
    """Test recover-destroyed-makers shows counts without applying changes."""
    with app.app_context():
        runner = app.test_cli_runner()
        result = runner.invoke(args=['definitions', 'recover-destroyed-makers'], input='n\n')
        
        assert result.exit_code == 0
        assert 'Current truncated maker counts:' in result.output
        assert 'Aston' in result.output
        assert 'Aborted' in result.output
        
        # Verify no changes were made
        maker = db.session.execute(text("""
            SELECT maker FROM vehicle_definitions WHERE source_id = 1001
        """)).scalar()
        assert maker == 'Aston'  # Still truncated


def test_recover_destroyed_makers_yes(app, destroyed_makers_data):
    """Test recover-destroyed-makers --yes applies all recoveries."""
    with app.app_context():
        runner = app.test_cli_runner()
        result = runner.invoke(args=['definitions', 'recover-destroyed-makers', '--yes'])
        
        assert result.exit_code == 0
        assert 'Recovering makers...' in result.output
        assert 'Aston → Aston Martin' in result.output
        assert 'MV → MV Agusta' in result.output
        assert 'Legend → Legend Cars' in result.output
        assert 'SCCA → SCCA Enterprises' in result.output
        assert 'BT1 → General Motors' in result.output
        assert '공통규격 → not_vehicle' in result.output
        assert 'Recovery complete' in result.output
        
        # Verify changes were applied
        makers = db.session.execute(text("""
            SELECT source_id, maker, powertrain FROM vehicle_definitions 
            WHERE source_id >= 1001
            ORDER BY source_id
        """)).fetchall()
        
        assert makers[0][1] == 'Aston Martin'
        assert makers[1][1] == 'MV Agusta'
        assert makers[2][1] == 'Legend Cars'
        assert makers[3][1] == 'SCCA Enterprises'
        assert makers[4][1] == 'General Motors'
        assert makers[5][2] == 'not_vehicle'  # powertrain changed


def test_recover_destroyed_makers_no_data(app):
    """Test recover-destroyed-makers when no truncated makers exist."""
    with app.app_context():
        runner = app.test_cli_runner()
        result = runner.invoke(args=['definitions', 'recover-destroyed-makers', '--yes'])
        
        assert result.exit_code == 0
        assert 'Recovering makers...' in result.output
        # Should report 0 rows for each recovery
