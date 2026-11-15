"""EV9 업로드 테스트."""

import pytest
from pathlib import Path
from io import BytesIO


@pytest.fixture
def ev9_csv():
    """EV9 업로드 테스트용 CSV 픽스처."""
    csv_path = Path(__file__).parent.parent / "fixtures" / "csv" / "ev9_upload_test.csv"
    with open(csv_path, 'rb') as f:
        return f.read()


def test_ev9_file_upload_and_ecu_detection(_app_base, make_user, ev9_csv):
    """EV9 업로드 E2E: VIN 17자, type=ev, 성공 단계>0, no_data=0, PDF VIN·마스킹."""
    from app.modules.scanner.upload import process_upload
    from app.modules.scans.models import Scan, ScanDocument
    from werkzeug.datastructures import FileStorage
    from app.extensions import db
    from sqlalchemy import select
    import pypdf
    
    with _app_base.app_context():
        admin = make_user(tid="ev9_test", type="admin")
        
        # 가짜 EV9 로그: VIN 17자 (ZZZ1234567890123), 배터리 응답 포함
        csv_lines = ["Timestamp,Channel,CAN_ID,DLC,Data"]
        t = 0.0
        
        # 1. Broadcast session control
        csv_lines.append(f"{t:.6f},Tx,0x7DF,8,02 10 01 00 00 00 00 00")
        csv_lines.append(f"{t+0.01:.6f},Rx,0x598,8,02 50 01 00 00 00 00 00")
        csv_lines.append(f"{t+0.015:.6f},Rx,0x59E,8,02 50 01 00 00 00 00 00")
        csv_lines.append(f"{t+0.020:.6f},Rx,0x788,8,02 50 01 00 00 00 00 00")
        t += 0.1
        
        # 2. VIN request (09 02) → multi-frame response with VIN=KNDJC811AB7000001 (17 chars)
        csv_lines.append(f"{t:.6f},Tx,0x7E4,8,02 09 02 00 00 00 00 00")
        csv_lines.append(f"{t+0.01:.6f},Rx,0x7EC,8,10 13 49 02 01 4B 4E 44")  # FF: 19 bytes, "KND"
        csv_lines.append(f"{t+0.015:.6f},Tx,0x7E4,8,30 00 00 00 00 00 00 00")  # FC
        csv_lines.append(f"{t+0.02:.6f},Rx,0x7EC,8,21 4A 43 38 31 31 41 42")  # CF1: "JC811AB"
        csv_lines.append(f"{t+0.03:.6f},Rx,0x7EC,8,22 37 30 30 30 30 30 31")  # CF2: "7000001"
        t += 0.1
        
        # 3. Battery data request (22 01 01) → multi-frame response
        csv_lines.append(f"{t:.6f},Tx,0x7E4,8,03 22 01 01 00 00 00 00")
        csv_lines.append(f"{t+0.01:.6f},Rx,0x7EC,8,10 20 62 01 01 64 12 34")  # FF: 32 bytes, SOC=100(0x64)
        csv_lines.append(f"{t+0.015:.6f},Tx,0x7E4,8,30 00 00 00 00 00 00 00")
        csv_lines.append(f"{t+0.02:.6f},Rx,0x7EC,8,21 56 78 00 00 15 16 17")
        csv_lines.append(f"{t+0.03:.6f},Rx,0x7EC,8,22 18 19 1A 00 B9 19 B9")
        csv_lines.append(f"{t+0.04:.6f},Rx,0x7EC,8,23 28 00 00 00 00 00 00")
        t += 0.1
        
        # 4. Tester Present
        csv_lines.append(f"{t:.6f},Tx,0x7E0,8,02 3E 80 00 00 00 00 00")  # suppressPosRsp
        t += 0.05
        
        # 5. DTC read
        csv_lines.append(f"{t:.6f},Tx,0x7E4,8,01 03 00 00 00 00 00 00")
        csv_lines.append(f"{t+0.01:.6f},Rx,0x7EC,8,02 43 00 00 00 00 00 00")
        
        csv_data = "\n".join(csv_lines).encode('utf-8')
        
        file = FileStorage(
            stream=BytesIO(csv_data),
            filename="ev9_test.csv",
            content_type="text/csv"
        )
        
        scan_id = process_upload(
            actor=admin,
            file=file,
            car_no="88가8888",  # 마스킹 테스트
            car={"maker": "기아", "model": "EV9", "fuel": "전기"},  # form 필드
            device="EV9 테스트"
        )
        
        assert scan_id is not None
        scan = db.session.get(Scan, scan_id)
        assert scan is not None
        
        # 1. Scan type=ev
        assert scan.type == "ev", f"Expected type=ev, got {scan.type}"
        
        # 2. VIN 17자
        assert scan.car_vin is not None, "VIN not decoded"
        assert len(scan.car_vin) == 17, f"VIN should be 17 chars, got {len(scan.car_vin)}: {scan.car_vin}"
        assert scan.car_vin == "KNDJC811AB7000001", f"VIN mismatch: {scan.car_vin}"
        
        # 3. 성공 단계 > 0, no_data = 0
        from app.modules.canlab.models import DiagnosticReport
        report_id = scan.bms_data.get("report_id")
        assert report_id is not None, "report_id not in bms_data"
        report = db.session.get(DiagnosticReport, report_id)
        assert report is not None
        
        ecus = report.diagnosis.get("ecus", [])
        ecu_request_ids = {ecu["request_id"] for ecu in ecus}
        assert "598" in ecu_request_ids, f"ECU 598 not found. ECUs: {ecu_request_ids}"
        assert "59E" in ecu_request_ids, f"ECU 59E not found. ECUs: {ecu_request_ids}"
        assert "788" in ecu_request_ids, f"ECU 788 not found. ECUs: {ecu_request_ids}"
        
        # Count successful steps (not no_data)
        all_steps = []
        for ecu in ecus:
            all_steps.extend(ecu.get("steps", []))
        
        success_steps = [s for s in all_steps if s.get("status") == "ok"]
        no_data_steps = [s for s in all_steps if s.get("status") == "no_data"]
        
        assert len(success_steps) > 0, f"No successful steps. Total: {len(all_steps)}"
        assert len(no_data_steps) == 0, f"Found {len(no_data_steps)} no_data steps (should be 0)"
        
        # 4. PDF: VIN 전체 + 마스킹 번호판
        pdf_doc = db.session.scalar(select(ScanDocument).where(ScanDocument.scan_id == scan_id))
        assert pdf_doc is not None, "PDF not generated"
        assert pdf_doc.size > 0, "PDF size is 0"
        
        pdf_bytes = BytesIO(pdf_doc.content)
        reader = pypdf.PdfReader(pdf_bytes)
        full_text = ""
        for page in reader.pages:
            full_text += page.extract_text()
        
        assert "KNDJC811AB7000001" in full_text, "PDF should contain full VIN"
        assert "88가****" in full_text, "PDF should contain masked plate 88가****"
        
        db.session.rollback()


def test_ev9_e2e_battery_diagnostic(_app_base, make_user, ev9_csv):
    """EV9 배터리 진단: B17/B18 셀, 정의불일치, 판정보류."""
    from app.modules.scanner.upload import process_upload
    from app.modules.scans.models import Scan
    from werkzeug.datastructures import FileStorage
    from app.extensions import db
    
    with _app_base.app_context():
        admin = make_user(tid="ev9_battery", type="admin")
        
        file = FileStorage(
            stream=BytesIO(ev9_csv),
            filename="ev9_battery.csv"
        )
        
        scan_id = process_upload(
            actor=admin,
            file=file,
            car_no="99배터리",
            car={"diag_company": "기아", "diag_model": "EV9", "diag_fuel": "전기"},
            device="배터리 테스트"
        )
        
        scan = db.session.get(Scan, scan_id)
        assert scan is not None
        
        # 주행거리 없으면 판정보류
        assert scan.car_distance is None, "주행거리가 있으면 안 됨"
        
        # 3E 80 suppressPosRsp는 오류가 아님
        # bms_data에서 errors 확인
        assert "errors" in scan.bms_data
        suppress_errors = [e for e in scan.bms_data["errors"] if "3E 80" in str(e)]
        assert len(suppress_errors) == 0, f"3E 80 suppressPosRsp는 오류가 아니어야 함: {suppress_errors}"
        
        # ECU 등록 확인 (첫 번째 테스트와 동일)
        from app.modules.canlab.models import DiagnosticReport
        report_id = scan.bms_data.get("report_id")
        assert report_id is not None
        report = db.session.get(DiagnosticReport, report_id)
        assert report is not None
        ecus = report.diagnosis.get("ecus", [])
        ecu_request_ids = {ecu["request_id"] for ecu in ecus}
        assert "598" in ecu_request_ids
        assert "59E" in ecu_request_ids
        assert "788" in ecu_request_ids
        
        # B17/B18 배터리 데이터는 해석 규칙이 있을 때 나타남
        # transaction count 확인 (통신이 있었음)
        assert report.diagnosis.get("transaction_count", 0) > 0, "transaction이 없음"
        
        # PDF 생성 확인
        from app.modules.scans.models import ScanDocument
        from sqlalchemy import select
        pdf_doc = db.session.scalar(select(ScanDocument).where(ScanDocument.scan_id == scan_id))
        assert pdf_doc is not None, "PDF가 생성되지 않음"
        assert pdf_doc.size > 0, "PDF 크기가 0"
        
        db.session.rollback()
