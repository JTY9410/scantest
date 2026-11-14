"""Tests for database audit CLI."""
import pytest
from sqlalchemy import text
from app.extensions import db


def test_audit_queries_work(app):
    """Verify audit SQL queries execute without errors."""
    with app.app_context():
        # Test all audit queries
        
        # Orphans check
        orphan_scans = db.session.execute(text("""
            SELECT COUNT(*) FROM scans 
            WHERE tester_id IS NOT NULL 
            AND NOT EXISTS (SELECT 1 FROM users WHERE id = scans.tester_id)
        """)).scalar()
        assert orphan_scans >= 0
        
        # Duplicates check
        dup_specs = db.session.execute(text("""
            SELECT COUNT(*) FROM (
                SELECT maker, model, trim_grade, model_year, COUNT(*) as cnt
                FROM battery_specs
                WHERE is_active = true
                GROUP BY maker, model, trim_grade, model_year
                HAVING COUNT(*) > 1
            ) sub
        """)).scalar()
        assert dup_specs >= 0
        
        # UNKNOWN ecu_module check
        unknown_cmd_ecu = db.session.execute(text("""
            SELECT COUNT(*) FROM diagnostic_commands
            WHERE ecu_module IS NULL OR UPPER(ecu_module) = 'UNKNOWN'
        """)).scalar()
        total_cmds = db.session.execute(text("SELECT COUNT(*) FROM diagnostic_commands")).scalar()
        assert unknown_cmd_ecu >= 0
        assert total_cmds >= 0
        
        # UNKNOWN signal_category check
        unknown_sig_cat = db.session.execute(text("""
            SELECT COUNT(*) FROM dbc_signals
            WHERE signal_category IS NULL 
            OR UPPER(signal_category) IN ('UNKNOWN', 'OTHER')
        """)).scalar()
        total_signals = db.session.execute(text("SELECT COUNT(*) FROM dbc_signals")).scalar()
        assert unknown_sig_cat >= 0
        assert total_signals >= 0
