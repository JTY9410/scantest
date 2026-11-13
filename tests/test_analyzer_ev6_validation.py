"""EV6 CSV fixture 디코딩 검증 테스트

물리적 타당성 및 기대값 검증
"""
from pathlib import Path

from app.extensions import db
from app.modules.scans.models import Scan
from app.modules.definitions.analyzer import load_csv_and_analyze
from app.modules.definitions.models import ScanObservation
from app.modules.accounts.models import User
from app.modules.accounts.passwords import hash_password


def test_ev6_decoded_values_plausible(app):
    """EV6 디코딩 값 물리적 타당성 검증"""
    
    with app.app_context():
        # 테스트 유저 생성
        tester = User(
            tid='tester_val',
            name='Validator',
            type='tester',
            password=hash_password('test123'),
        )
        db.session.add(tester)
        db.session.commit()
        
        # 스캔 생성
        scan = Scan(
            type='ev',
            device_type='test',
            device_uid='test-val',
            tester_id=tester.id,
            car_no='12가****',
            car_maker='Kia',
            car_model='EV6',
            car_year=2022,
            car_vin='KNDC*****',
        )
        db.session.add(scan)
        db.session.commit()
        
        # CSV 로드 및 분석
        csv_path = Path('tests/fixtures/ev6_file_b_scantest_measured.csv')
        result = load_csv_and_analyze(csv_path, scan)
        
        battery = result.get('battery', {})
        
        # SOC 범위 검증 (0-100%)
        if 'soc_pct' in battery:
            assert 0 <= battery['soc_pct'] <= 100, \
                f"SOC out of range: {battery['soc_pct']}%"
            print(f"✓ SOC: {battery['soc_pct']}%")
        
        # SOH 범위 검증 (0-100%, 약간 여유)
        if 'soh_pct' in battery:
            assert 0 <= battery['soh_pct'] <= 110, \
                f"SOH out of range: {battery['soh_pct']}%"
            print(f"✓ SOH: {battery['soh_pct']}%")
        
        # 팩 전압 검증 (EV6: ~500-850V)
        if 'pack_voltage_v' in battery:
            assert 500 <= battery['pack_voltage_v'] <= 850, \
                f"Pack voltage out of range: {battery['pack_voltage_v']}V"
            print(f"✓ Pack voltage: {battery['pack_voltage_v']}V")
        
        # 전류 검증 (±600A)
        if 'pack_current_a' in battery:
            assert -600 <= battery['pack_current_a'] <= 600, \
                f"Current out of range: {battery['pack_current_a']}A"
            print(f"✓ Current: {battery['pack_current_a']}A")
        
        # 온도 검증 (-40 to 100°C)
        for temp_key in ['max_temp_c', 'min_temp_c']:
            if temp_key in battery:
                temp = battery[temp_key]
                assert -40 <= temp <= 100, \
                    f"{temp_key} out of range: {temp}°C"
                print(f"✓ {temp_key}: {temp}°C")
        
        # 셀 전압 검증 (2.5-4.3V)
        for cell_key in ['max_cell_voltage_v', 'min_cell_voltage_v']:
            if cell_key in battery:
                cell_v = battery[cell_key]
                assert 2.5 <= cell_v <= 4.3, \
                    f"{cell_key} out of range: {cell_v}V"
                print(f"✓ {cell_key}: {cell_v}V")
        
        # 무효 값이 없는지 확인
        invalid_keys = [k for k in battery.keys() if k.endswith('_invalid')]
        assert len(invalid_keys) == 0, \
            f"Invalid values found: {invalid_keys}"
        
        print(f"\n✅ All {len(battery)} battery values are physically plausible")
        
        # 통계 검증
        assert result['definitions_applied']['successful_decodes'] > 0
        assert result['definitions_applied']['frames_processed'] == 854
        assert result['definitions_applied']['isotp_reassembled'] > 400


def test_ev6_no_sentinel_values(app):
    """0xFF/0xFFFF 센티널 값이 결과에 없는지 확인"""
    
    with app.app_context():
        tester = User(
            tid='tester_sent',
            name='Sentinel Checker',
            type='tester',
            password=hash_password('test123'),
        )
        db.session.add(tester)
        db.session.commit()
        
        scan = Scan(
            type='ev',
            device_type='test',
            device_uid='test-sent',
            tester_id=tester.id,
            car_no='12가****',
            car_maker='Kia',
            car_model='EV6',
            car_year=2022,
        )
        db.session.add(scan)
        db.session.commit()
        
        csv_path = Path('tests/fixtures/ev6_file_b_scantest_measured.csv')
        result = load_csv_and_analyze(csv_path, scan)
        
        battery = result.get('battery', {})
        
        # 센티널 값 체크
        for key, value in battery.items():
            if isinstance(value, int):
                assert value not in [0xFF, 0xFFFF, 0xFFFFFFFF], \
                    f"{key} contains sentinel value: {value:#x}"
            elif isinstance(value, float):
                # mV로 변환했을 때 센티널이 아닌지
                if 'voltage' in key.lower():
                    mv_value = int(value * 1000)
                    assert mv_value not in [0xFFFF, 0xFFFFFFFF], \
                        f"{key} = {value}V ({mv_value}mV) is sentinel"
        
        print(f"✅ No sentinel values (0xFF/0xFFFF) in {len(battery)} battery fields")


def test_ev6_observations_recorded(app):
    """ScanObservation 학습 데이터 기록 확인"""
    
    with app.app_context():
        tester = User(
            tid='tester_obs',
            name='Observation Logger',
            type='tester',
            password=hash_password('test123'),
        )
        db.session.add(tester)
        db.session.commit()
        
        scan = Scan(
            type='ev',
            device_type='test',
            device_uid='test-obs',
            tester_id=tester.id,
            car_no='12가****',
            car_maker='Kia',
            car_model='EV6',
            car_year=2022,
        )
        db.session.add(scan)
        db.session.commit()
        
        csv_path = Path('tests/fixtures/ev6_file_b_scantest_measured.csv')
        result = load_csv_and_analyze(csv_path, scan)
        
        # Observations 조회
        observations = db.session.query(ScanObservation).filter_by(scan_id=scan.id).all()
        
        assert len(observations) > 0, "No observations recorded"
        
        # 성공/실패 분류
        successful = [o for o in observations if o.success]
        failed = [o for o in observations if not o.success]
        
        print(f"✓ Recorded {len(observations)} observations")
        print(f"  - Successful: {len(successful)}")
        print(f"  - Failed (for learning): {len(failed)}")
        
        # 실패한 관찰에는 mismatch_reason이 있어야 함
        for obs in failed:
            assert obs.mismatch_reason is not None, \
                "Failed observation must have mismatch_reason"
        
        print(f"✅ All failed observations have mismatch reasons for learning")


def test_ev6_realistic_battery_state(app):
    """EV6 배터리 상태가 현실적인지 통합 검증"""
    
    with app.app_context():
        tester = User(
            tid='tester_real',
            name='Reality Checker',
            type='tester',
            password=hash_password('test123'),
        )
        db.session.add(tester)
        db.session.commit()
        
        scan = Scan(
            type='ev',
            device_type='test',
            device_uid='test-real',
            tester_id=tester.id,
            car_no='12가****',
            car_maker='Kia',
            car_model='EV6',
            car_year=2022,
        )
        db.session.add(scan)
        db.session.commit()
        
        csv_path = Path('tests/fixtures/ev6_file_b_scantest_measured.csv')
        result = load_csv_and_analyze(csv_path, scan)
        
        battery = result.get('battery', {})
        
        # 기대값 범위 (파일명 "scantest_measured" 기준)
        # 주차 중이므로 전류 ~0A, 온도 실온 범위 등
        
        if 'pack_current_a' in battery:
            # 정차 중이므로 전류가 작아야 함
            assert abs(battery['pack_current_a']) < 50, \
                f"Unexpected high current while parked: {battery['pack_current_a']}A"
            print(f"✓ Parked current: {battery['pack_current_a']}A (< 50A)")
        
        if 'max_temp_c' in battery and 'min_temp_c' in battery:
            # 온도 편차가 크지 않아야 함 (냉각 시스템 정상)
            temp_diff = abs(battery['max_temp_c'] - battery['min_temp_c'])
            assert temp_diff < 30, \
                f"Excessive temperature spread: {temp_diff}°C"
            print(f"✓ Temperature spread: {temp_diff}°C (< 30°C)")
        
        if 'soh_pct' in battery:
            # SOH는 100% 이하여야 함 (신차 아님)
            assert battery['soh_pct'] < 100, \
                f"SOH should be < 100% for used vehicle: {battery['soh_pct']}%"
            # 80% 이상이어야 정상
            assert battery['soh_pct'] >= 80, \
                f"SOH too low: {battery['soh_pct']}%"
            print(f"✓ SOH: {battery['soh_pct']}% (80-100% range)")
        
        if 'cum_charge_kwh' in battery and 'cum_discharge_kwh' in battery:
            # 효율 검증 (방전/충전 비율 70-95%)
            efficiency = battery['cum_discharge_kwh'] / battery['cum_charge_kwh'] * 100
            assert 70 <= efficiency <= 95, \
                f"Unrealistic efficiency: {efficiency:.1f}%"
            print(f"✓ Battery efficiency: {efficiency:.1f}% (70-95% range)")
        
        print(f"\n✅ EV6 battery state is realistic for parked vehicle")
