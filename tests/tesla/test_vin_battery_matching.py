"""Test Tesla VIN decoding and battery reference matching."""

import pytest
from app.modules.tesla.vin_decoder import decode_tesla_vin


class TestTeslaVINDecoder:
    """Test VIN decoder with real Tesla VIN patterns."""
    
    def test_decode_model_s_2017(self):
        """Test Model S 2017 VIN decode."""
        vin = "5YJSA1E26HF123456"  # Fake VIN: Model S, 2017
        decoded = decode_tesla_vin(vin)
        
        assert decoded['wmi'] == '5YJ'
        assert decoded['model_code'] == 'S'
        assert decoded['model'] == 'Model S'
        assert decoded['year_code'] == 'H'
        assert decoded['year'] == 2017
        assert decoded['motor_code'] == '2'  # Position 8 = index 7
        assert decoded['plant_code'] == 'F'
        assert decoded['valid'] is True
    
    def test_decode_model_3_2020(self):
        """Test Model 3 2020 VIN decode."""
        vin = "5YJ3E1EA7LF123456"  # Fake VIN: Model 3, 2020
        decoded = decode_tesla_vin(vin)
        
        assert decoded['model_code'] == '3'
        assert decoded['model'] == 'Model 3'
        assert decoded['year_code'] == 'L'
        assert decoded['year'] == 2020
        assert decoded['valid'] is True
    
    def test_decode_model_y_2021(self):
        """Test Model Y 2021 VIN decode."""
        vin = "5YJYGDEE5MF123456"  # Fake VIN: Model Y, 2021
        decoded = decode_tesla_vin(vin)
        
        assert decoded['model_code'] == 'Y'
        assert decoded['model'] == 'Model Y'
        assert decoded['year_code'] == 'M'
        assert decoded['year'] == 2021
        assert decoded['valid'] is True


@pytest.mark.parametrize("vin,expected_model,expected_year,expected_status", [
    # Model S 2017: multiple packs (75/75D/90D/100D/P100D) → 팩 후보 다수
    ("5YJSA1E26HF123456", "Model S", 2017, "팩 후보 다수"),
    # Model 3 2020: if single match → SOH computed, if multiple → 팩 후보 다수
    ("5YJ3E1EA7LF123456", "Model 3", 2020, None),  # depends on DB
    # Model Y 2021: depends on candidates
    ("5YJYGDEE5MF123456", "Model Y", 2021, None),
])
def test_tesla_battery_matching_with_real_vin_decode(app, vin, expected_model, expected_year, expected_status):
    """Test battery reference matching with proper VIN decode.
    
    Uses fake VINs with correct Model/Year encoding.
    """
    with app.app_context():
        from app.modules.scans.battery_soh import find_matching_references, prepare_soh_report_data
        from app.modules.scans.battery_capacity import BatteryReferenceCapacity
        from app.extensions import db
        
        # Seed Model S packs for 2017 (multiple candidates)
        if expected_model == 'Model S' and expected_year == 2017:
            # Clear existing
            BatteryReferenceCapacity.query.filter_by(maker='Tesla', model='Model S', year_from=2017).delete()
            
            packs = [
                {'trim': '75', 'gross_capacity_kwh': 75.0},
                {'trim': '75D', 'gross_capacity_kwh': 75.0},
                {'trim': '90D', 'gross_capacity_kwh': 90.0},
                {'trim': '100D', 'gross_capacity_kwh': 100.0},
                {'trim': 'P100D', 'gross_capacity_kwh': 100.0},
            ]
            for pack in packs:
                ref = BatteryReferenceCapacity(
                    maker='Tesla',
                    model='Model S',
                    trim=pack['trim'],
                    year_from=2017,
                    year_to=2017,
                    gross_capacity_kwh=pack['gross_capacity_kwh'],
                    verification_level='2차 자료 기반 후보값',
                    source_url_1='https://ev-database.org',
                    vin_wmi='5YJ'
                )
                db.session.add(ref)
            db.session.commit()
        
        # Seed Model 3 pack for 2020 (single candidate for testing)
        elif expected_model == 'Model 3' and expected_year == 2020:
            BatteryReferenceCapacity.query.filter_by(maker='Tesla', model='Model 3', year_from=2020).delete()
            ref = BatteryReferenceCapacity(
                maker='Tesla',
                model='Model 3',
                trim='Long Range',
                year_from=2020,
                year_to=2020,
                gross_capacity_kwh=82.0,
                verification_level='2차 자료 기반 후보값',
                source_url_1='https://ev-database.org',
                vin_wmi='5YJ'
            )
            db.session.add(ref)
            db.session.commit()
        
        # Seed Model Y pack for 2021
        elif expected_model == 'Model Y' and expected_year == 2021:
            BatteryReferenceCapacity.query.filter_by(maker='Tesla', model='Model Y', year_from=2021).delete()
            ref = BatteryReferenceCapacity(
                maker='Tesla',
                model='Model Y',
                trim='Long Range',
                year_from=2021,
                year_to=2021,
                gross_capacity_kwh=75.0,
                verification_level='2차 자료 기반 후보값',
                source_url_1='https://ev-database.org',
                vin_wmi='5YJ'
            )
            db.session.add(ref)
            db.session.commit()
        
        # Find matches using VIN (will decode internally)
        candidates = find_matching_references(
            maker='Tesla',
            model='Ignored',  # VIN decode will override
            year=None,  # VIN decode will override
            vin=vin
        )
        
        print(f"\n=== Test: {expected_model} {expected_year} ===")
        print(f"VIN: {vin}")
        print(f"Candidates found: {len(candidates)}")
        for i, c in enumerate(candidates, 1):
            print(f"  {i}. {c.model} {c.trim} ({c.year_from}-{c.year_to}) - {c.gross_capacity_kwh} kWh")
        
        # Verify model and year match from VIN decode
        if candidates:
            assert all(c.model == expected_model for c in candidates), \
                f"All candidates must be {expected_model}"
            assert all(c.year_from <= expected_year <= (c.year_to or expected_year) for c in candidates), \
                f"All candidates must cover year {expected_year}"
        
        # Prepare SOH report
        current_capacity = 65.0
        soh_report = prepare_soh_report_data(
            current_capacity_kwh=current_capacity,
            current_capacity_type='gross',
            maker='Tesla',
            model='Ignored',  # VIN decode overrides
            year=None,
            vin=vin
        )
        
        print(f"\nSOH Report:")
        print(f"  Status: {soh_report.get('soh_status', 'OK')}")
        print(f"  SOH: {soh_report.get('soh_percent')}")
        print(f"  Candidates: {len(soh_report.get('candidates', []))}")
        
        # Check expected status
        if expected_status == "팩 후보 다수":
            assert '팩 후보 다수' in soh_report.get('soh_status', ''), \
                "Multiple candidates should show '팩 후보 다수'"
            assert soh_report.get('soh_percent') is None, \
                "SOH should not be computed with multiple candidates"
            assert len(soh_report['candidates']) > 1, \
                "Should have multiple candidates"
        elif expected_status is None and len(candidates) == 1:
            # Single candidate: SOH should be computed
            assert soh_report.get('soh_percent') is not None, \
                "SOH should be computed with single candidate"
            assert '2차 자료 기준(참고)' in soh_report.get('reference_source', ''), \
                "2nd-hand source should be labeled"
