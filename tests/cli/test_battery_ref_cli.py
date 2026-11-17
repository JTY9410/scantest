"""Test battery reference CLI commands."""

import pytest
from sqlalchemy import text
from pathlib import Path


def test_battery_ref_seed_command(app):
    """Test that flask battery-ref-seed command works via CLI runner."""
    with app.app_context():
        from app.extensions import db
        
        # Clear any existing data
        db.session.execute(text("DELETE FROM battery_reference_capacity"))
        db.session.commit()
        
        # Run the CLI command
        runner = app.test_cli_runner()
        result = runner.invoke(args=['battery-ref-seed'])
        
        assert result.exit_code == 0, f"Command failed: {result.output}"
        
        # Verify data was seeded (223 - 2 Land Rover rows with NULL capacities = 221)
        count = db.session.execute(text("SELECT COUNT(*) FROM battery_reference_capacity")).scalar()
        assert count == 221, f"Expected 221 rows (actual verified count from xlsx), got {count}"
        
        # Verify PK044 and PK045 are present
        pk044 = db.session.execute(text(
            "SELECT COUNT(*) FROM battery_reference_capacity WHERE pack_id = 'PK044'"
        )).scalar()
        pk045 = db.session.execute(text(
            "SELECT COUNT(*) FROM battery_reference_capacity WHERE pack_id = 'PK045'"
        )).scalar()
        
        assert pk044 > 0, "PK044 not found"
        assert pk045 > 0, "PK045 not found"


def test_battery_ref_import_command(app):
    """Test that flask battery-ref-import command works via CLI runner."""
    with app.app_context():
        from app.extensions import db
        
        # Clear any existing data
        db.session.execute(text("DELETE FROM battery_reference_capacity"))
        db.session.commit()
        
        # Run the CLI command with import7 file
        runner = app.test_cli_runner()
        import7_path = Path(__file__).parent.parent.parent / 'data' / 'battery_reference' / 'import7_brands_capacity_master.xlsx'
        result = runner.invoke(args=['battery-ref-import', str(import7_path)])
        
        assert result.exit_code == 0, f"Command failed: {result.output}"
        assert 'Successfully imported' in result.output
        
        # Verify data was imported (22 - 2 Land Rover with NULL capacities = 20)
        count = db.session.execute(text("SELECT COUNT(*) FROM battery_reference_capacity")).scalar()
        assert count == 20, f"Expected 20 rows from import7 (22 - 2 NULL capacity), got {count}"


def test_entrypoint_commands_are_registered(app):
    """Test that all flask commands called in docker/web-entrypoint.sh are registered."""
    # Read entrypoint script
    entrypoint_path = Path(__file__).parent.parent.parent / 'docker' / 'web-entrypoint.sh'
    entrypoint_content = entrypoint_path.read_text()
    
    # Extract flask commands from entrypoint
    import re
    flask_commands = re.findall(r'flask\s+([a-z-]+)', entrypoint_content)
    
    # Get all registered CLI commands
    registered_commands = set(app.cli.commands.keys())
    
    # Verify each flask command in entrypoint is registered
    for cmd in flask_commands:
        assert cmd in registered_commands, \
            f"Command 'flask {cmd}' used in entrypoint but not registered in app.cli.commands"


def test_seed_replaces_null_capacity_rows(app):
    """Test that seed removes rows with ALL capacity columns NULL (unusable for SOH)."""
    with app.app_context():
        from app.extensions import db
        from app.modules.scans.battery_capacity import BatteryReferenceCapacity
        
        # Clear and insert a bad row (ALL capacities NULL, like leftover opendbc data)
        db.session.execute(text("DELETE FROM battery_reference_capacity"))
        db.session.commit()
        
        bad_row = BatteryReferenceCapacity(
            maker='Tesla',
            model='Model 3',
            year_from=2018,
            year_to=2021,
            gross_capacity_kwh=None,      # NULL
            net_capacity_kwh=None,        # NULL
            official_capacity_kwh=None,   # NULL - all three NULL = unusable
            warnings='opendbc PACK_74_KWH',
        )
        db.session.add(bad_row)
        db.session.commit()
        
        # Run seed
        runner = app.test_cli_runner()
        result = runner.invoke(args=['battery-ref-seed'])
        
        assert result.exit_code == 0, f"Command failed: {result.output}"
        
        # Verify rows with ALL capacity columns NULL were removed
        null_count = db.session.execute(text("""
            SELECT COUNT(*) FROM battery_reference_capacity 
            WHERE gross_capacity_kwh IS NULL 
              AND net_capacity_kwh IS NULL 
              AND official_capacity_kwh IS NULL
        """)).scalar()
        
        assert null_count == 0, f"Found {null_count} rows with all NULL capacities after seed"
        
        # Verify good data was imported (excluding NULL capacity rows)
        total_count = db.session.execute(text("SELECT COUNT(*) FROM battery_reference_capacity")).scalar()
        assert total_count == 221, f"Expected 221 rows (actual verified count from xlsx), got {total_count}"


def test_version_is_correct(app):
    """Test that app version is 2.2.18."""
    from app.__version__ import __version__
    assert __version__ == "2.2.20", f"Expected version 2.2.20, got {__version__}"
