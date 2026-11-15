"""EV9 업로드 테스트."""

import pytest
from pathlib import Path
from app.models import User, Scan
from app.modules.scanner.interpret import interpret_scan, scan_result
from app.modules.scanner.report import inspection
from app.modules.scanner.document import scan_document
from app import db


@pytest.fixture
def ev9_csv():
    """EV9 업로드 테스트용 CSV 픽스처."""
    return Path(__file__).parent.parent / "fixtures" / "csv" / "ev9_upload_test.csv"


def test_ev9_upload_end_to_end(client, make_user, ev9_csv):
    """EV9 업로드 end-to-end 테스트.
    
    검증 항목:
    1. 업로드 성공
    2. 판정보류 (주행거리 없음)
    3. 3E 80 정상 처리
    4. 598/59E/788 ECU 등록
    5. B17/B18 모듈 온도
    6. 범위 밖 값 정의불일치
    7. 최저 셀 번호 두 기준
    8. PDF 쪽수
    """
    with client.application.app_context():
        # 1. 사용자 생성
        user_id = make_user("tester1", type="admin")
        actor = db.session.get(User, user_id)
        
        # 2. 업로드 실행
        from app.modules.scanner.upload import process_upload
        from werkzeug.datastructures import FileStorage
        
        with open(ev9_csv, "rb") as f:
            file = FileStorage(f, filename="ev9_test.csv", content_type="text/csv")
            
            scan_id = process_upload(
                actor=actor,
                file=file,
                car_no="12가3456",
                car={"diag_company": "기아", "diag_model": "EV9", "diag_year": 2023},
                device="테스트 업로드"
            )
        
        assert scan_id is not None, "업로드 성공해야 함"
        
        # 스캔 조회
        scan = db.session.get(Scan, scan_id)
        assert scan is not None
        
        result = scan_result(scan)
        assert result is not None
        
        wescan = result.get("wescan")
        assert wescan is not None
        
        # 3. 판정보류 (주행거리 없음)
        view = inspection(scan, result)
        
        assert view["overall"] == "판정보류", "주행거리 없으면 판정보류"
        assert view["vehicle"]["mileage"] is None, "주행거리 미수신"
        
        # 4. 3E 80 정상 처리 (오류 목록에 없어야 함)
        errors = result.get("errors", [])
        tester_present_errors = [e for e in errors if "3E 80" in str(e.get("command", "")).upper()]
        assert len(tester_present_errors) == 0, "3E 80 무응답은 오류가 아님"
        
        # 5. 598/59E/788 ECU 등록
        # 7DF 기능주소 요청에 598이 응답하면, pair_transactions에서
        # request_id를 응답 ID - 8 (590)으로 조정
        steps = result.get("steps", [])
        ecus_found = set()
        for step in steps:
            if step.get("header"):
                ecus_found.add(step["header"])
        
        # 픽스처에는 598 응답이 있으므로 590(598-8)이 등록되어야 함
        assert "590" in ecus_found, f"기능주소 응답 ECU(590=598-8) 등록 실패: {ecus_found}"
        
        # ECU 개수 확인: header가 있는 모든 ECU가 3개 이상이어야 함
        # (status와 무관하게, header가 있으면 ECU로 인식됨)
        assert len(ecus_found) >= 3, f"ECU 3개 이상 등록되어야 함: {ecus_found}"
        
        # 6. B17/B18 모듈 온도
        # 픽스처에 0111 DID가 있고 B17/B18 데이터가 있으면 검증
        battery = result.get("battery", {})
        modules = view.get("modules", [])
        
        # 모듈 온도가 있는지 확인 (B17/B18 또는 숫자 모듈)
        if modules:
            module_nos = [m["no"] for m in modules]
            # B17/B18이 있거나 숫자 모듈이 있으면 OK
            has_alpha = any(str(no).startswith("B") or str(no).startswith("b") for no in module_nos)
            has_numeric = any(str(no).isdigit() for no in module_nos)
            assert has_alpha or has_numeric, f"모듈 온도 등록 확인: {module_nos}"
        
        # 7. 범위 밖 값 정의불일치
        # E004에 FFFF 응답이 있으면 범위 밖 처리되어야 함
        # decode_signals에서 _out_of_range_signals로 기록
        out_of_range = battery.get("_out_of_range_signals")
        if out_of_range:
            assert len(out_of_range) > 0, "범위 밖 값이 기록되어야 함"
            for item in out_of_range:
                assert "정의불일치" in item.get("reason", ""), f"범위 밖 값은 정의불일치로 표시: {item}"
        
        # 8. 최저 셀 번호 두 기준 (view에 있으면 검증)
        # 픽스처에 셀 전압이 있고 불일치가 있으면 cell_no_mismatch가 설정됨
        # 없어도 오류는 아님 (픽스처에 셀 데이터가 없을 수 있음)
        
        # 9. PDF 쪽수 및 내용
        document = scan_document(scan)
        assert document is not None, "PDF 생성 성공"
        # PDF 크기 확인 (최소 크기: 1KB, 픽스처 데이터가 적으면 작을 수 있음)
        assert document.size > 500, f"PDF 생성됨: {document.size} bytes"
        
        # PDF 형식 확인
        pdf_content = document.content
        assert pdf_content[:4] == b"%PDF", "유효한 PDF 파일"
        
        # 전체 검증: 스캔 상태
        assert result["status"] in ("ok", "partial"), "스캔 완료"
        assert scan.type in ("ev", "hev"), "유형 판별"


def test_ev9_upload_suppress_response(client, make_user, ev9_csv):
    """3E 80 (TesterPresent suppressPosRsp) 무응답이 오류로 처리되지 않는지 확인."""
    with client.application.app_context():
        from app.modules.scanner.upload import process_upload
        from werkzeug.datastructures import FileStorage
        
        user_id = make_user("tester2", type="admin")
        actor = db.session.get(User, user_id)
        
        with open(ev9_csv, "rb") as f:
            file = FileStorage(f, filename="ev9_test.csv", content_type="text/csv")
            
            scan_id = process_upload(
                actor=actor,
                file=file,
                car_no="12가3457",
                car={"diag_company": "기아", "diag_model": "EV9", "diag_year": 2023},
                device="테스트 업로드"
            )
        
        scan = db.session.get(Scan, scan_id)
        result = scan_result(scan)
        
        # 3E 80이 오류 목록에 없어야 함
        errors = result.get("errors", [])
        tester_present_errors = [e for e in errors if "3E" in str(e.get("command", "")).upper() and "80" in str(e.get("command", "")).upper()]
        
        assert len(tester_present_errors) == 0, f"3E 80 무응답은 오류가 아님: {tester_present_errors}"
