"""EV6 CSV fixture로 실제 디코딩 테스트"""
from pathlib import Path

from app.extensions import db
from app.modules.scans.models import Scan
from app.modules.definitions.analyzer import load_csv_and_analyze
from app.modules.definitions.models import ScanObservation
from app.modules.accounts.models import User
from app.modules.accounts.passwords import hash_password


def test_analyzer_ev6_real_decode(app):
    """EV6 CSV 실제 디코딩 및 WESCAN 결과 생성"""
    
    with app.app_context():
        # 테스트 유저 생성
        tester = User(
            tid='tester123',
            name='Test Tester',
            type='tester',
            password=hash_password('test123'),
        )
        db.session.add(tester)
        db.session.commit()
        
        # 스캔 생성
        scan = Scan(
            type='ev',
            device_type='test',
            device_uid='test-123',
            tester_id=tester.id,
            car_no='12가****',  # 마스킹
            car_maker='Kia',
            car_model='EV6',
            car_year=2022,
            car_vin='KNDC*****',  # 마스킹
        )
        db.session.add(scan)
        db.session.commit()
        
        # CSV 로드 및 분석
        csv_path = Path('tests/fixtures/ev6_file_b_scantest_measured.csv')
        print(f"\n=== Loading and Analyzing: {csv_path.name} ===")
        
        result = load_csv_and_analyze(csv_path, scan)
        
        # 결과 출력
        print(f"\n=== Analysis Result ===")
        print(f"\nVehicle:")
        for key, value in result['vehicle'].items():
            print(f"  {key}: {value}")
        
        print(f"\nDefinitions Applied:")
        for key, value in result['definitions_applied'].items():
            print(f"  {key}: {value}")
        
        print(f"\nBattery Data: {len(result.get('battery', {}))} fields")
        if result.get('battery'):
            print("\nBattery Values:")
            for key, value in result['battery'].items():
                if isinstance(value, (int, float)):
                    print(f"  {key}: {value}")
                elif isinstance(value, list):
                    print(f"  {key}: {value[:5]}... ({len(value)} values)")
                else:
                    print(f"  {key}: {value}")
        
        print(f"\nVehicle Info: {len(result.get('vehicle_info', {}))} fields")
        if result.get('vehicle_info'):
            print("\nVehicle Info Values:")
            for key, value in sorted(result['vehicle_info'].items()):
                print(f"  {key}: {value}")
        
        print(f"\nPowertrain Data: {len(result.get('powertrain', {}))} fields")
        
        print(f"\nDTCs: {len(result.get('dtcs', []))}")
        
        # ScanObservation 통계
        observations = db.session.query(ScanObservation).filter_by(scan_id=scan.id).all()
        print(f"\n=== Scan Observations ===")
        print(f"Total rows written: {len(observations)}")
        
        if observations:
            success = sum(1 for o in observations if o.success)
            failed = len(observations) - success
            print(f"  Successful decodes: {success}")
            print(f"  Failed decodes: {failed}")
            
            # 성공한 샘플
            successful = [o for o in observations if o.success][:5]
            if successful:
                print(f"\nSample Decoded Observations:")
                for obs in successful:
                    print(f"  - {obs.decoded_value[:80] if obs.decoded_value else '(no value)'}")
        
        # WESCAN 스타일 요약
        print(f"\n=== WESCAN-Style Summary ===")
        print(f"Frames processed: {result['definitions_applied']['frames_processed']}")
        print(f"ISO-TP reassembled: {result['definitions_applied']['isotp_reassembled']}")
        print(f"Successful decodes: {result['definitions_applied']['successful_decodes']}")
        print(f"Failed decodes: {result['definitions_applied']['failed_decodes']}")
        
        # 주요 값 테이블
        if result.get('battery') or result.get('vehicle_info'):
            print(f"\n=== Key Decoded Values (Sample) ===")
            print(f"{'Name':<30} {'Value':<15} {'Unit':<10}")
            print("-" * 55)
            
            # Battery
            for key, value in list(result.get('battery', {}).items())[:5]:
                if isinstance(value, list):
                    display = f"{value[0]:.1f}..." if value else "[]"
                else:
                    display = f"{value:.1f}" if isinstance(value, float) else str(value)
                print(f"{key:<30} {display:<15} {'':10}")
            
            # Vehicle info
            for key, value in list(result.get('vehicle_info', {}).items())[:5]:
                display = f"{value:.1f}" if isinstance(value, float) else str(value)[:15]
                print(f"{key:<30} {display:<15} {'':10}")
        
        print(f"\n✅ Real decoding completed")
        
        # 검증
        assert result is not None
        assert result['definitions_applied']['frames_processed'] > 0
        assert result['definitions_applied']['successful_decodes'] > 0
        assert len(observations) > 0
