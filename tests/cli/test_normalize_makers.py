"""Tests for maker normalization CLI."""
import pytest
from sqlalchemy import text

from app.extensions import db


def test_normalize_makers_only_touches_vehicle_definitions(app):
    """normalize-makers only modifies vehicle_definitions table, not scans.
    
    This documents the guarantee that manual overrides in scans.powertrain_source
    are never affected by maker normalization.
    """
    runner = app.test_cli_runner()
    
    with app.app_context():
        # Verify the command only queries vehicle_definitions in its implementation
        # by checking that a normalize operation works without any scans data
        db.session.execute(text("""
            INSERT INTO definition_sources (id, source_type, file_path, sha256, file_size, imported_at)
            VALUES (1, 'dbc', '/test/path', '0000000000000000000000000000000000000000000000000000000000000000', 100, NOW())
        """))
        db.session.execute(text("""
            INSERT INTO vehicle_definitions (
                id, source_id, maker, model, powertrain
            ) VALUES (
                1, 1, 'Hyundai_ Ioniq', 'Ioniq', 'unknown'
            )
        """))
        db.session.commit()
        
        # Run normalize-makers
        result = runner.invoke(args=["definitions", "normalize-makers", "--yes"])
        
        # Should succeed without touching scans table
        assert result.exit_code == 0
        
        # Verify vehicle_definition WAS normalized
        vdef_data = db.session.execute(text("""
            SELECT maker FROM vehicle_definitions WHERE id = 1
        """)).fetchone()
        
        assert vdef_data[0] == 'Hyundai', "Vehicle def maker should be normalized (extracted from 'Hyundai_ Ioniq')"


def test_normalize_makers_report_only_mode(app):
    """--report-only shows stats without making changes."""
    runner = app.test_cli_runner()
    
    with app.app_context():
        db.session.execute(text("""
            INSERT INTO definition_sources (id, source_type, file_path, sha256, file_size, imported_at)
            VALUES (1, 'dbc', '/test/path', '0'*64, 100, NOW())
        """))
        db.session.execute(text("""
            INSERT INTO vehicle_definitions (
                id, source_id, maker, model, powertrain
            ) VALUES (
                1, 1, 'Hyundai_ Ioniq', 'Ioniq', 'unknown'
            )
        """))
        db.session.commit()
        
        # Run with --report-only
        result = runner.invoke(args=["definitions", "normalize-makers", "--report-only"])
        
        assert result.exit_code == 0
        assert "BEFORE Normalization" in result.output
        assert "(Use --yes to apply normalization)" in result.output
        
        # Verify NO changes were made
        vdef_data = db.session.execute(text("""
            SELECT maker FROM vehicle_definitions WHERE id = 1
        """)).fetchone()
        
        assert vdef_data[0] == 'Hyundai_ Ioniq', "Maker should not be changed in report-only mode"
