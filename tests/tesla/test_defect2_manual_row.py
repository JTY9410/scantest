"""Test that manual Tesla 74kWh row doesn't override catalog matches (Defect 2)."""

import pytest


def test_seed_produces_221_rows_not_222(app):
    """Verify seed produces exactly 221 rows (no manual Tesla row)."""
    from app.modules.scans.battery_capacity import BatteryReferenceCapacity
    from app import db
    
    with app.app_context():
        # Run seed
        runner = app.test_cli_runner()
        result = runner.invoke(args=["battery-ref-seed"])
        assert result.exit_code == 0, f"Seed failed: {result.output}"
        
        # Check count
        count = db.session.query(BatteryReferenceCapacity).count()
        assert count == 221, f"Expected 221 rows (actual verified count from xlsx), got {count}"
        
        # No manual rows should exist
        manual_count = db.session.query(BatteryReferenceCapacity).filter_by(
            source_file="manual"
        ).count()
        assert manual_count == 0, f"Found {manual_count} manual rows, expected 0"


def test_fake_tesla_model3_vin_gives_multiple_candidates(app):
    """Test fake 5YJ3 2020 Model 3 VIN matches PK024, PK031, PK039."""
    from app.modules.scans.battery_soh import find_matching_references
    from app import db
    
    with app.app_context():
        # Seed first
        runner = app.test_cli_runner()
        runner.invoke(args=["battery-ref-seed"])
        
        # Test with fake VIN
        vin = "5YJ3E1EA0LF000001"  # 2020 Model 3
        matches = find_matching_references(
            maker="Tesla",
            model="Model 3",
            year=2020,
            trim=None,
            vin=vin
        )
        
        assert len(matches) >= 3, f"Expected at least 3 candidates, got {len(matches)}"
        
        # Check for expected pack IDs
        pack_ids = {m.pack_id for m in matches}
        expected = {"PK024", "PK031", "PK039"}
        assert expected.issubset(pack_ids), f"Expected {expected}, got {pack_ids}"
        
        # Check capacities
        by_pack = {m.pack_id: m for m in matches}
        assert abs(by_pack["PK024"].gross_capacity_kwh - 53.1) < 0.1, "PK024 should be 53.1 kWh"
        assert abs(by_pack["PK031"].gross_capacity_kwh - 78.8) < 0.1, "PK031 should be 78.8 kWh"
        assert abs(by_pack["PK039"].gross_capacity_kwh - 78.8) < 0.1, "PK039 should be 78.8 kWh"


def test_tesla_soh_without_trim_heuristic(app):
    """Test Tesla SOH calculation doesn't use capacity-based trim heuristic."""
    from app.modules.tesla.soh import calculate_soh
    from app import db
    
    with app.app_context():
        runner = app.test_cli_runner()
        runner.invoke(args=["battery-ref-seed"])
        
        # 75 kWh pack should NOT get 'Long Range' trim (old heuristic was current_full > 60)
        result = calculate_soh(
            current_nominal_full=75.0,
            manufacturer="Tesla",
            model="Model 3",
            year=2020,
            pack_code=None,  # No heuristic-generated trim
            bol_energy=None,
            vin="5YJ3E1EA0LF000001"
        )
        
        # Should find multiple candidates
        candidates = result.get('candidates', [])
        assert len(candidates) >= 3, f"Expected multiple candidates, got {len(candidates)}"
        
        # Should be 미산정 (undetermined) due to multiple candidates
        assert result['soh_available'] == False
        assert '팩 후보 다수' in result.get('calculation_note', '') or '미산정' in result.get('calculation_note', '')
