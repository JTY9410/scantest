"""SOH 계산기 테스트."""
import pytest
from app.modules.battery.soh_calculator import SOHCalculator
from app.modules.battery.models import BatterySpec, SOHResult
from app.modules.scans.models import Scan
from app.modules.accounts.models import User
from app.modules.accounts.passwords import hash_password
from app.extensions import db


def test_soh_bms_direct(app):
    """BMS 직접 읽기 방법 테스트."""
    with app.app_context():
        scan_data = {
            'battery': {'soh_pct': 92.5},
            'vehicle': {'maker': '현대', 'model': 'EV6', 'year': 2022}
        }
        
        results = SOHCalculator.calculate(scan_data)
        
        assert len(results) >= 1
        assert results[0].method == 'bms_direct'
        assert results[0].soh_pct == 92.5
        assert results[0].confidence == 0.95
        assert results[0].method_label_ko == 'BMS 직접 읽기'


def test_soh_capacity_based(app):
    """현재 용량 기반 방법 테스트."""
    with app.app_context():
        # 배터리 사양 생성
        spec = BatterySpec(
            maker='현대',
            model='EV6',
            trim_grade='Long Range',
            model_year=2022,
            usable_kwh=74.0,
            capacity_ah=111,
            source_url='https://test.com'
        )
        db.session.add(spec)
        db.session.commit()
        
        # 현재 용량 있는 스캔
        scan_data = {
            'battery': {'current_capacity_ah': 100.0},
            'vehicle': {'maker': '현대', 'model': 'EV6', 'year': 2022}
        }
        
        results = SOHCalculator.calculate(scan_data)
        
        # capacity_based_ah 방법이 있어야 함
        capacity_result = next((r for r in results if r.method == 'capacity_based_ah'), None)
        assert capacity_result is not None
        assert abs(capacity_result.soh_pct - 90.1) < 0.5  # 100/111 * 100
        assert capacity_result.confidence == 0.90


def test_soh_coulomb_counting(app):
    """Coulomb Counting 방법 테스트."""
    with app.app_context():
        spec = BatterySpec(
            maker='기아',
            model='Niro EV',
            capacity_ah=180,
            cell_chemistry='NMC',
            source_url='https://test.com'
        )
        db.session.add(spec)
        db.session.commit()
        
        scan_data = {
            'battery': {
                'cum_charge_ah': 9000.0,
                'cum_discharge_ah': 8500.0
            },
            'vehicle': {'maker': '기아', 'model': 'Niro EV', 'year': 2019}
        }
        
        results = SOHCalculator.calculate(scan_data)
        
        coulomb_result = next((r for r in results if r.method == 'coulomb_counting'), None)
        assert coulomb_result is not None
        assert 60 <= coulomb_result.soh_pct <= 110  # 타당한 범위
        assert coulomb_result.confidence >= 0.70


def test_soh_multiple_methods(app):
    """여러 방법이 적용될 때 우선순위 테스트."""
    with app.app_context():
        spec = BatterySpec(
            maker='현대',
            model='IONIQ 5',
            usable_kwh=68.0,
            capacity_ah=104,
            cell_chemistry='NMC',
            source_url='https://test.com'
        )
        db.session.add(spec)
        db.session.commit()
        
        # BMS SOH + 현재 용량 + Coulomb counting 모두 가능
        scan_data = {
            'battery': {
                'soh_pct': 95.0,  # BMS
                'current_capacity_ah': 98.0,  # Capacity-based
                'cum_charge_ah': 5000.0,  # Coulomb counting
                'cum_discharge_ah': 4800.0
            },
            'vehicle': {'maker': '현대', 'model': 'IONIQ 5', 'year': 2021}
        }
        
        results = SOHCalculator.calculate(scan_data)
        
        # 최소 3개 방법 적용
        assert len(results) >= 3
        
        # 우선순위: BMS > Capacity > Coulomb
        assert results[0].method == 'bms_direct'
        assert results[0].confidence > results[1].confidence  # 신뢰도 순


def test_soh_result_storage(app):
    """SOH 결과 DB 저장 테스트."""
    with app.app_context():
        # 테스트 사용자 및 스캔 생성
        user = User(
            tid='test_soh',
            name='Test',
            type='tester',
            password=hash_password('test123')
        )
        db.session.add(user)
        db.session.commit()
        
        scan = Scan(
            type='ev',
            device_type='test',
            device_uid='test-soh',
            tester_id=user.id,
            car_no='12가****',
            car_vin='TEST*****',
            car_maker='현대',
            car_model='EV6',
            car_year=2022
        )
        db.session.add(scan)
        db.session.commit()
        
        scan_data = {
            'battery': {'soh_pct': 88.5},
            'vehicle': {'maker': '현대', 'model': 'EV6', 'year': 2022}
        }
        
        # scan_id와 함께 계산 (저장됨)
        results = SOHCalculator.calculate(scan_data, scan.id)
        
        # DB에 저장되었는지 확인
        saved_results = db.session.query(SOHResult).filter_by(scan_id=scan.id).all()
        assert len(saved_results) >= 1
        assert saved_results[0].soh_pct == 88.5
        assert saved_results[0].method == 'bms_direct'
        assert saved_results[0].bms_soh_pct == 88.5  # Ground truth


def test_soh_ground_truth_error(app):
    """Ground truth와 오차 계산 테스트."""
    with app.app_context():
        spec = BatterySpec(
            maker='기아',
            model='EV6',
            capacity_ah=111,
            source_url='https://test.com'
        )
        db.session.add(spec)
        db.session.commit()
        
        user = User(tid='test2', name='Test', type='tester', password=hash_password('test'))
        db.session.add(user)
        db.session.commit()
        
        scan = Scan(
            type='ev',
            device_type='test',
            device_uid='test-gt',
            tester_id=user.id,
            car_no='12가****',
            car_vin='TEST*****',
            car_maker='기아',
            car_model='EV6',
            car_year=2022
        )
        db.session.add(scan)
        db.session.commit()
        
        scan_data = {
            'battery': {
                'soh_pct': 90.0,  # BMS (ground truth)
                'current_capacity_ah': 100.0  # 예측: 90.1%
            },
            'vehicle': {'maker': '기아', 'model': 'EV6', 'year': 2022}
        }
        
        SOHCalculator.calculate(scan_data, scan.id)
        
        # capacity_based 결과 확인
        capacity_result = db.session.query(SOHResult).filter_by(
            scan_id=scan.id,
            method='capacity_based_ah'
        ).first()
        
        if capacity_result:
            assert capacity_result.bms_soh_pct == 90.0
            assert capacity_result.error_pct is not None
            assert abs(capacity_result.error_pct - 0.1) < 0.5  # 오차 ~0%


def test_soh_unrated_when_no_data(app):
    """데이터 없을 때 unrated 테스트."""
    with app.app_context():
        # 아무 데이터도 없는 스캔
        scan_data = {
            'battery': {},
            'vehicle': {'maker': 'Unknown', 'model': 'Unknown'}
        }
        
        results = SOHCalculator.calculate(scan_data)
        
        # 결과 없거나 매우 낮은 신뢰도만
        assert len(results) == 0 or (len(results) > 0 and results[0].confidence <= 0.60)


def test_soh_priority_order(app):
    """SOH 계산 방법 우선순위 검증 테스트.
    
    우선순위 (2026-10-18 기술개발 정의):
    1. BMS SOH 직접 읽기 (0.95)
    2. 현재 용량 ÷ 공칭 용량 (0.85-0.90)
    3. Coulomb counting (0.75)
    4. Energy counting (0.70)
    5. OCV-SOC (0.60)
    6. Internal resistance (0.55)
    7. Throughput heuristic (0.40, fallback)
    """
    with app.app_context():
        spec = BatterySpec(
            maker='현대',
            model='IONIQ 5',
            capacity_ah=104,
            gross_kwh=72.6,
            usable_kwh=68.0,
            source_url='https://www.hyundai.com/spec.pdf'
        )
        db.session.add(spec)
        db.session.commit()
        
        # All methods available
        scan_data = {
            'battery': {
                'soh_pct': 95.0,  # BMS direct
                'current_capacity_ah': 98.0,  # Capacity-based
                'cum_charge_ah': 5000.0,
                'cum_discharge_ah': 4800.0,  # Coulomb counting
                'cum_charge_kwh': 3400.0,
                'cum_discharge_kwh': 3200.0,  # Energy counting
                'ocv_v': 350.0,
                'soc_pct': 50.0,  # OCV-SOC
                'internal_resistance_mohm': 45.0,  # Resistance
                'odometer_km': 50000  # Throughput heuristic
            },
            'vehicle': {'maker': '현대', 'model': 'IONIQ 5', 'year': 2021}
        }
        
        results = SOHCalculator.calculate(scan_data)
        
        # All methods should be present
        assert len(results) >= 3
        
        # Verify priority order by confidence
        for i in range(len(results) - 1):
            assert results[i].confidence >= results[i+1].confidence, \
                f"Priority violation: {results[i].method} ({results[i].confidence}) should have higher confidence than {results[i+1].method} ({results[i+1].confidence})"
        
        # First result should be BMS direct
        assert results[0].method == 'bms_direct'
        assert results[0].confidence == 0.95
        
    # Verify BMS direct read reference
    assert 'BMS direct read' in results[0].calculation_details.get('source', '')


def test_soh_confidence_levels(app):
    """SOH 방법별 confidence 레벨 검증."""
    with app.app_context():
        spec = BatterySpec(
            maker='기아',
            model='EV6',
            capacity_ah=111,
            cell_chemistry='NMC',  # Required for coulomb_counting confidence 0.75
            source_url='https://www.kia.com/spec.pdf'
        )
        db.session.add(spec)
        db.session.commit()
        
        # Test each method individually
        test_cases = [
            ({'soh_pct': 90.0}, 'bms_direct', 0.95),
            ({'current_capacity_ah': 100.0}, 'capacity_based_ah', 0.90),
            ({'cum_charge_ah': 5000.0, 'cum_discharge_ah': 4800.0}, 'coulomb_counting', 0.75),
        ]
        
        for battery_data, expected_method, expected_confidence in test_cases:
            scan_data = {
                'battery': battery_data,
                'vehicle': {'maker': '기아', 'model': 'EV6', 'year': 2022}
            }
            
            results = SOHCalculator.calculate(scan_data)
            
            method_result = next((r for r in results if r.method == expected_method), None)
            assert method_result is not None, f"Method {expected_method} not found"
            assert method_result.confidence == expected_confidence, \
                f"Expected confidence {expected_confidence} for {expected_method}, got {method_result.confidence}"


def test_soh_calculation_basis_recorded(app):
    """SOH 계산 근거와 입력값이 기록되는지 검증."""
    with app.app_context():
        user = User(
            tid='test_basis',
            name='Test',
            type='tester',
            password=hash_password('test123')
        )
        db.session.add(user)
        db.session.commit()
        
        scan = Scan(
            type='ev',
            device_type='test',
            device_uid='test-basis',
            tester_id=user.id,
            car_no='12가****',
            car_vin='TEST12345',  # Required field
            car_maker='현대',
            car_model='EV6',
            car_year=2022
        )
        db.session.add(scan)
        db.session.commit()
        
        scan_data = {
            'battery': {'soh_pct': 92.0},
            'vehicle': {'maker': '현대', 'model': 'EV6', 'year': 2022}
        }
        
        SOHCalculator.calculate(scan_data, scan.id)
        
        # Check saved result
        result = db.session.query(SOHResult).filter_by(scan_id=scan.id).first()
        
        assert result is not None
        assert result.method == 'bms_direct'
        assert result.input_features is not None
        assert 'bms_soh_pct' in result.input_features
        assert result.calculation_details is not None
        assert 'source' in result.calculation_details
        assert result.confidence == 0.95
