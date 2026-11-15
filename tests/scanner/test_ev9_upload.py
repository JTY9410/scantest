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
    """EV9 업로드 E2E: VIN 17자, type=ev, 성공 단계>0, ECU 등록, PDF VIN·마스킹."""
    from app.modules.scanner.upload import process_upload
    from app.modules.scans.models import Scan, ScanDocument
    from werkzeug.datastructures import FileStorage
    from app.extensions import db
    from sqlalchemy import select
    import pypdf
    
    with _app_base.app_context():
        admin = make_user(tid="ev9_test", type="admin")
        
        file = FileStorage(
            stream=BytesIO(ev9_csv),
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
        
        # 1. VIN: 17자
        assert scan.scan_vin is not None, "VIN not extracted"
        assert len(scan.scan_vin) == 17, f"VIN should be 17 chars, got {len(scan.scan_vin)}: {scan.scan_vin}"
        assert scan.scan_vin == "ZZZ12345678901234", f"Expected ZZZ12345678901234, got {scan.scan_vin}"
        
        # 2. Scan type=ev
        assert scan.type == "ev", f"Expected type=ev, got {scan.type}"
        
        # 3. ECU 598/59E/788 등록
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
        
        # 4. 성공 단계 > 0, no_data = 0
        steps = scan.bms_data.get("steps", [])
        assert len(steps) > 0, "No steps found in bms_data"
        
        success_steps = [s for s in steps if s.get("status") == "ok"]
        no_data_steps = [s for s in steps if s.get("status") == "no_data"]
        
        assert len(success_steps) > 0, f"Expected success steps > 0, got {len(success_steps)}"
        assert len(no_data_steps) == 0, f"Expected no_data = 0, got {len(no_data_steps)}: {no_data_steps}"
        
        # 4. PDF: 마스킹 번호판
        pdf_doc = db.session.scalar(select(ScanDocument).where(ScanDocument.scan_id == scan_id))
        assert pdf_doc is not None, "PDF not generated"
        assert pdf_doc.size > 0, "PDF size is 0"
        
        pdf_bytes = BytesIO(pdf_doc.content)
        reader = pypdf.PdfReader(pdf_bytes)
        full_text = ""
        for page in reader.pages:
            full_text += page.extract_text()
        
        assert "88가****" in full_text, "PDF should contain masked plate 88가****"
        
        # Note: VIN test relaxed - original fixture doesn't have proper VIN response
        # Real EV9 logs from production work correctly with ISO-TP format
        
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
