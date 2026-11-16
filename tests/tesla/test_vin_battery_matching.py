"""Test Tesla VIN decoding and battery reference matching with real xlsx data."""

import pytest
from app.modules.tesla.vin_decoder import decode_tesla_vin


class TestTeslaVINDecoder:
    """Test VIN decoder with real Tesla VIN patterns."""
    
    def test_decode_model_s_2017(self):
        vin = "5YJSA1E26HF123456"
        decoded = decode_tesla_vin(vin)
        assert decoded['model'] == 'Model S'
        assert decoded['year'] == 2017
    
    def test_decode_model_3_2020(self):
        vin = "5YJ3E1EA7LF123456"
        decoded = decode_tesla_vin(vin)
        assert decoded['model'] == 'Model 3'
        assert decoded['year'] == 2020
    
    def test_decode_model_y_2021(self):
        vin = "5YJYGDEE5MF123456"
        decoded = decode_tesla_vin(vin)
        assert decoded['model'] == 'Model Y'
        assert decoded['year'] == 2021


@pytest.mark.parametrize("vin,expected_model,expected_year,expected_pack_ids,expected_kwhs", [
    # Model S 2017: multiple packs → 팩 후보 다수
    ("5YJSA1E26HF123456", "Model S", 2017, ["PK001", "PK002"], [75.0, 90.0]),
    # Model 3 2020 (5YJ): PK024 SR+ 53.1, PK031 LR AWD 78.8, PK039 Perf 78.8
    ("5YJ3E1EA7LF123456", "Model 3", 2020, ["PK024", "PK031", "PK039"], [53.1, 78.8, 78.8]),
    # Model Y 2021 (5YJ): PK045 LR AWD 82.1, PK055 Perf 82.1 (NOT PK044 which is LRW)
    ("5YJYGDEE5MF123456", "Model Y", 2021, ["PK045", "PK055"], [82.1, 82.1]),
    # Model Y 2021 (LRW Shanghai): PK044 75.0 only
    ("LRWYGDEE5MF123456", "Model Y", 2021, ["PK044"], [75.0]),
])
def test_tesla_real_pack_matching(app, vin, expected_model, expected_year, expected_pack_ids, expected_kwhs):
    """Test with real xlsx pack data."""
    with app.app_context():
        from app.modules.scans.battery_soh import find_matching_references, prepare_soh_report_data
        from app.modules.scans.battery_capacity import BatteryReferenceCapacity
        from app.extensions import db
        
        # Clear and seed exact data from xlsx
        BatteryReferenceCapacity.query.filter_by(maker='Tesla', model=expected_model).delete()
        
        for i, (pack_id, kwh) in enumerate(zip(expected_pack_ids, expected_kwhs)):
            wmi = vin[:3] if vin.startswith(('5YJ', 'LRW')) else '5YJ'
            ref = BatteryReferenceCapacity(
                maker='Tesla',
                model=expected_model,
                trim=f'Trim-{i+1}',
                pack_id=pack_id,
                year_from=expected_year,
                year_to=expected_year,
                gross_capacity_kwh=kwh,
                verification_level='2차 자료 기반 후보값',
                source_url_1='https://ev-database.org',
                vin_wmi=wmi
            )
            db.session.add(ref)
        db.session.commit()
        
        # Find matches
        candidates = find_matching_references(
            maker='Tesla',
            model='Ignored',
            year=None,
            vin=vin
        )
        
        print(f"\n=== {expected_model} {expected_year} VIN {vin[:6]}... ===")
        print(f"Candidates: {len(candidates)}")
        for c in candidates:
            print(f"  {c.pack_id}: {c.gross_capacity_kwh} kWh WMI={c.vin_wmi}")
        
        # Assert exact pack IDs
        actual_pack_ids = sorted([c.pack_id for c in candidates])
        assert actual_pack_ids == sorted(expected_pack_ids), \
            f"Expected {expected_pack_ids}, got {actual_pack_ids}"
        
        # Assert capacities
        actual_kwhs = sorted([c.gross_capacity_kwh for c in candidates])
        assert actual_kwhs == sorted(expected_kwhs), \
            f"Expected {expected_kwhs} kWh, got {actual_kwhs}"
        
        # Prepare SOH report
        current = 65.0
        soh = prepare_soh_report_data(current, 'gross', 'Tesla', 'Ignored', None, None, vin)
        
        print(f"SOH Status: {soh.get('soh_status', 'OK')}")
        print(f"SOH: {soh.get('soh_percent')}")
        
        # Multiple candidates → 팩 후보 다수
        if len(candidates) > 1:
            assert '팩 후보 다수' in soh.get('soh_status', ''), "Multiple packs → 팩 후보 다수"
            assert soh.get('soh_percent') is None, "SOH 미산정"
        else:
            assert soh.get('soh_percent') is not None, "Single pack → SOH computed"
            assert '2차 자료 기준(참고)' in soh.get('reference_source', ''), "2차 label"
