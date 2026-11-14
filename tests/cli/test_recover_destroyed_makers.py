"""Integration tests for recover-destroyed-makers CLI command."""
import pytest
from sqlalchemy import text
from app.extensions import db


@pytest.fixture
def destroyed_makers_data(app):
    """Create test data with truncated maker names."""
    with app.app_context():
        # Create test sources with file paths indicating full maker names
        # Use different sha256 for each to avoid unique constraint violation
        db.session.execute(text("""
            INSERT INTO definition_sources (source_type, file_path, sha256, file_size, imported_at)
            VALUES 
                ('dbc', '/data/dbc/Aston_Martin_DB11.dbc', :sha1, 100, NOW()),
                ('dbc', '/data/dbc/MV_Agusta_F4.dbc', :sha2, 100, NOW()),
                ('dbc', '/data/dbc/Legend_Cars_34.dbc', :sha3, 100, NOW())
        """), {
            'sha1': 'a' + '0' * 63,
            'sha2': 'b' + '0' * 63,
            'sha3': 'c' + '0' * 63
        })
        db.session.commit()
        
        # Get source IDs
        sources = db.session.execute(text("""
            SELECT id, file_path FROM definition_sources 
            WHERE file_path LIKE '/data/dbc/%'
            ORDER BY file_path
        """)).fetchall()
        
        aston_id = sources[0][0]
        legend_id = sources[1][0]
        mv_id = sources[2][0]
        
        # Create vehicle definitions with truncated makers
        db.session.execute(text("""
            INSERT INTO vehicle_definitions (source_id, maker, model, powertrain, created_at)
            VALUES 
                (:aston_id, 'Aston', 'DB11', 'ICE', NOW()),
                (:mv_id, 'MV', 'F4', 'ICE', NOW()),
                (:legend_id, 'Legend', '34', 'ICE', NOW())
        """), {'aston_id': aston_id, 'mv_id': mv_id, 'legend_id': legend_id})
        db.session.commit()
        
        yield {
            'aston_id': aston_id,
            'mv_id': mv_id,
            'legend_id': legend_id
        }
        
        # Cleanup
        db.session.execute(text("""
            DELETE FROM vehicle_definitions 
            WHERE source_id IN (
                SELECT id FROM definition_sources WHERE file_path LIKE '/data/dbc/%'
            )
        """))
        db.session.execute(text("""
            DELETE FROM definition_sources WHERE file_path LIKE '/data/dbc/%'
        """))
        db.session.commit()


def test_recover_destroyed_makers_report_mode(app, destroyed_makers_data):
    """Test recover-destroyed-makers shows counts and requires confirmation."""
    with app.app_context():
        runner = app.test_cli_runner()
        result = runner.invoke(args=['definitions', 'recover-destroyed-makers'], input='n\n')
        
        assert result.exit_code == 0
        assert 'Current truncated maker counts:' in result.output
        assert 'Aston: 1 rows' in result.output
        assert 'MV: 1 rows' in result.output
        assert 'Legend: 1 rows' in result.output
        assert 'Aborted' in result.output
        
        # Verify no changes were made
        makers = db.session.execute(text("""
            SELECT maker FROM vehicle_definitions 
            WHERE source_id = :aston_id
        """), {'aston_id': destroyed_makers_data['aston_id']}).fetchall()
        
        assert makers[0][0] == 'Aston'  # Still truncated


def test_recover_destroyed_makers_yes(app, destroyed_makers_data):
    """Test recover-destroyed-makers --yes applies all recoveries."""
    with app.app_context():
        runner = app.test_cli_runner()
        result = runner.invoke(args=['definitions', 'recover-destroyed-makers', '--yes'])
        
        assert result.exit_code == 0
        assert 'Recovering makers...' in result.output
        assert 'Aston → Aston Martin: 1 rows' in result.output
        assert 'MV → MV Agusta: 1 rows' in result.output
        assert 'Legend → Legend Cars: 1 rows' in result.output
        assert 'Recovery complete' in result.output
        
        # Verify changes were applied
        makers = db.session.execute(text("""
            SELECT maker FROM vehicle_definitions 
            WHERE source_id IN (:aston_id, :mv_id, :legend_id)
            ORDER BY source_id
        """), destroyed_makers_data).fetchall()
        
        assert makers[0][0] == 'Aston Martin'
        assert makers[1][0] == 'Legend Cars'
        assert makers[2][0] == 'MV Agusta'


def test_recover_destroyed_makers_no_data(app):
    """Test recover-destroyed-makers when no truncated makers exist."""
    with app.app_context():
        runner = app.test_cli_runner()
        result = runner.invoke(args=['definitions', 'recover-destroyed-makers', '--yes'])
        
        assert result.exit_code == 0
        assert 'Recovering makers...' in result.output
        assert 'Recovery complete' in result.output
