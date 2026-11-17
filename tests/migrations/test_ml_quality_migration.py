"""Test ML Quality Analysis migration round-trip (v2.2.22)."""
import pytest


def test_ml_quality_migration_roundtrip(migrator):
    """Test upgrade and downgrade of ML quality tables."""
    # Start from the previous migration
    migrator.migrate_up_before("20261117_120000")
    
    # Verify tables don't exist yet
    assert not migrator.has_table("scan_quality_signals")
    assert not migrator.has_table("improvement_proposals")
    assert not migrator.has_table("proposal_audit_log")
    assert not migrator.has_table("versioned_configs")
    
    # Migrate up to ML quality migration
    migrator.migrate_up_to("20261117_120000")
    
    # Verify tables exist
    assert migrator.has_table("scan_quality_signals")
    assert migrator.has_table("improvement_proposals")
    assert migrator.has_table("proposal_audit_log")
    assert migrator.has_table("versioned_configs")
    
    # Verify key columns exist
    assert migrator.has_column("scan_quality_signals", "decode_failures")
    assert migrator.has_column("scan_quality_signals", "unmeasurable_items")
    assert migrator.has_column("scan_quality_signals", "dtc_status_unknown_count")
    
    assert migrator.has_column("improvement_proposals", "status")
    assert migrator.has_column("improvement_proposals", "evidence")
    assert migrator.has_column("improvement_proposals", "config_delta")
    assert migrator.has_column("improvement_proposals", "generation_method")
    
    assert migrator.has_column("proposal_audit_log", "action")
    assert migrator.has_column("proposal_audit_log", "user_email")
    
    assert migrator.has_column("versioned_configs", "active")
    assert migrator.has_column("versioned_configs", "config_value")
    
    # Migrate down
    migrator.migrate_down_to("20261117_110000")
    
    # Verify tables removed
    assert not migrator.has_table("scan_quality_signals")
    assert not migrator.has_table("improvement_proposals")
    assert not migrator.has_table("proposal_audit_log")
    assert not migrator.has_table("versioned_configs")
