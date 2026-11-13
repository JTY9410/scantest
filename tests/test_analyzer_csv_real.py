"""EV6 CSV fixture로 analyzer 실제 실행 및 결과 출력"""
import csv
from pathlib import Path

from app.extensions import db
from app.modules.scans.models import Scan
from app.modules.definitions.analyzer import analyze_scan_with_definitions
from app.modules.definitions.models import ScanObservation, DiagnosticCommand, VehicleDefinition
from app.modules.accounts.models import User
from app.modules.accounts.passwords import hash_password


def test_analyzer_real_csv(app):
    """EV6 CSV fixture 데이터로 analyzer 실제 실행 및 WESCAN 결과 검증"""
    
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
        
        # CSV 파일 읽기
        csv_path = Path('tests/fixtures/ev6_file_b_scantest_measured.csv')
        print(f"\n=== Loading CSV: {csv_path.name} ===")
        
        can_frames = []
        with open(csv_path, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                can_frames.append({
                    'timestamp': row['Timestamp'],
                    'can_id': row['CAN_ID'],
                    'data': row['Data'],
                })
        
        print(f"Loaded {len(can_frames)} CAN frames")
        
        # 차량 및 정의 정보 확인
        kia_defs = db.session.query(VehicleDefinition).filter_by(maker='Kia').count()
        ev6_defs = db.session.query(VehicleDefinition).filter(
            VehicleDefinition.maker == 'Kia',
            VehicleDefinition.model.like('%EV6%')
        ).count()
        total_commands = db.session.query(DiagnosticCommand).count()
        
        print(f"\n=== Definition Database ===")
        print(f"Kia definitions: {kia_defs}")
        print(f"EV6 definitions: {ev6_defs}")
        print(f"Total diagnostic commands: {total_commands}")
        
        # Scan 생성 (raw 필드에 CAN 데이터 저장)
        scan = Scan(
            type='ev',
            device_type='test',
            device_uid='test-123',
            tester_id=tester.id,
            car_no='12가3456',
            car_maker='Kia',
            car_model='EV6',
            car_year=2022,
            car_vin='KNDC*****TEST****',
            raw={'can_frames': can_frames[:100]},  # 샘플 100개만
        )
        db.session.add(scan)
        db.session.commit()
        
        print(f"\n=== Created Scan #{scan.id} ===")
        print(f"Vehicle: {scan.car_maker} {scan.car_model} ({scan.car_year})")
        print(f"CAN frames in raw: {len(scan.raw.get('can_frames', []))}")
        
        # Analyzer 실행
        print(f"\n=== Running Analyzer ===")
        result = analyze_scan_with_definitions(scan)
        
        # 결과 출력
        print(f"\n=== WESCAN-Style Analysis Result ===")
        print(f"\nVehicle:")
        for key, value in result['vehicle'].items():
            print(f"  {key}: {value}")
        
        print(f"\nDefinitions Applied:")
        for key, value in result['definitions_applied'].items():
            print(f"  {key}: {value}")
        
        battery = result.get('battery', {})
        print(f"\nBattery Data: {len(battery)} fields")
        if battery:
            for key, value in list(battery.items())[:5]:
                print(f"  {key}: {value}")
            if len(battery) > 5:
                print(f"  ... and {len(battery) - 5} more")
        
        powertrain = result.get('powertrain', {})
        print(f"\nPowertrain Data: {len(powertrain)} fields")
        if powertrain:
            for key, value in list(powertrain.items())[:5]:
                print(f"  {key}: {value}")
            if len(powertrain) > 5:
                print(f"  ... and {len(powertrain) - 5} more")
        
        dtcs = result.get('dtcs', [])
        print(f"\nDTCs: {len(dtcs)}")
        if dtcs:
            for dtc in dtcs[:3]:
                print(f"  - {dtc}")
            if len(dtcs) > 3:
                print(f"  ... and {len(dtcs) - 3} more")
        
        # ScanObservation 개수 확인
        observations = db.session.query(ScanObservation).filter_by(scan_id=scan.id).all()
        print(f"\n=== Scan Observations ===")
        print(f"Total rows created: {len(observations)}")
        
        if observations:
            success = sum(1 for o in observations if o.success)
            failed = len(observations) - success
            print(f"  Decoded successfully: {success}")
            print(f"  Failed to decode: {failed}")
            
            # 성공한 샘플 출력
            successful_obs = [o for o in observations if o.success][:3]
            if successful_obs:
                print(f"\nSample Decoded Values:")
                for obs in successful_obs:
                    if obs.definition_id > 0:
                        cmd = db.session.query(DiagnosticCommand).get(obs.definition_id)
                        if cmd:
                            print(f"  - {cmd.label or cmd.command_bytes}: {obs.decoded_value}")
                    else:
                        print(f"  - {obs.decoded_value[:50]}")
        
        print(f"\n✅ Analyzer execution completed")
        
        # 검증
        assert result is not None
        assert 'vehicle' in result
        assert 'definitions_applied' in result
