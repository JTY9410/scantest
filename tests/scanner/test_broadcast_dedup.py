"""브로드캐스트 중복 제거 테스트 (EV9 스타일)."""

import pytest
from io import BytesIO
from werkzeug.datastructures import FileStorage


def test_broadcast_deduplication_keeps_steps_under_600(_app_base, make_user):
    """수백 번 반복되는 브로드캐스트 로그를 업로드해도 단계 수가 600 이하."""
    from app.modules.scanner.upload import process_upload
    from app.modules.scans.models import Scan
    from app.extensions import db
    
    # 위스캔 CSV 형식: 브로드캐스트 요청-응답을 100회 반복
    csv_lines = ["Timestamp,Channel,CAN_ID,DLC,Data"]
    
    # 100회 반복
    for i in range(100):
        t = i * 0.1
        
        # 7DF 브로드캐스트: 10 01 (Start Diagnostic Session)
        csv_lines.append(f"{t:.6f},1,000007DF,8,02 10 01 00 00 00 00 00")
        csv_lines.append(f"{t+0.01:.6f},1,00000598,8,06 50 01 00 32 01 F4 00")
        csv_lines.append(f"{t+0.015:.6f},1,0000059E,8,06 50 01 00 32 01 F4 00")
        csv_lines.append(f"{t+0.020:.6f},1,00000788,8,06 50 01 00 32 01 F4 00")
        
        # 7DF 브로드캐스트: 3E 80 (Tester Present suppressPosRp)
        csv_lines.append(f"{t+0.05:.6f},1,000007DF,8,02 3E 80 00 00 00 00 00")
        # suppressPosRp이므로 응답 없음
    
    csv_content = "\n".join(csv_lines)
    
    with _app_base.app_context():
        admin_id = make_user(tid="dedup_admin", type="admin")
        
        file = FileStorage(
            stream=BytesIO(csv_content.encode()),
            filename="ev9_broadcast_repeated.csv",
            content_type="text/csv"
        )
        
        # 업로드 처리
        scan_id = process_upload(
            actor=admin_id,
            file=file,
            car_no="88가8888",
            device="Broadcast Dedup Test"
        )
        
        assert scan_id is not None
        scan = db.session.get(Scan, scan_id)
        assert scan is not None
        
        # bms_data에 단계 수 확인 (steps 또는 counts에 기록됨)
        bms_data = scan.bms_data or {}
        steps = bms_data.get("steps", [])
        
        # 단계 수가 600 이하여야 함
        assert len(steps) <= 600, f"단계 수 {len(steps)}개가 600개 초과"
        
        # 실제로는 훨씬 적어야 함 (세션 제어 + 기타)
        # ECU 3개 × 세션 제어 1개 = 3단계 정도
        assert len(steps) < 50, f"단계 수 {len(steps)}개가 예상보다 많음 (기대: ~10개)"
        
        db.session.rollback()


def test_broadcast_upload_returns_200_not_400(_app_base, make_user, admin_client):
    """브로드캐스트 중복 제거 후 업로드가 400이 아니라 200으로 성공."""
    from app.extensions import db
    
    # 위스캔 CSV: 200회 반복
    csv_lines = ["Timestamp,Channel,CAN_ID,DLC,Data"]
    
    for i in range(200):
        t = i * 0.05
        csv_lines.append(f"{t:.6f},1,000007DF,8,02 10 01 00 00 00 00 00")
        csv_lines.append(f"{t+0.01:.6f},1,00000598,8,06 50 01 00 32 01 F4 00")
        csv_lines.append(f"{t+0.015:.6f},1,0000059E,8,06 50 01 00 32 01 F4 00")
        csv_lines.append(f"{t+0.020:.6f},1,00000788,8,06 50 01 00 32 01 F4 00")
    
    csv_content = "\n".join(csv_lines)
    
    with _app_base.app_context():
        make_user(tid="upload_admin", type="admin", password="testpass")
    
    # 로그인
    admin_client.post("/admin/login", data={"tid": "upload_admin", "password": "testpass"})
    
    # 업로드
    response = admin_client.post(
        "/admin/scan/upload",
        data={
            "file": (BytesIO(csv_content.encode()), "broadcast_test.csv"),
            "car_no": "88가8888",
        },
        content_type="multipart/form-data"
    )
    
    # 400 오류가 아니어야 함
    assert response.status_code != 400, f"업로드 실패: {response.get_data(as_text=True)}"
    
    # 성공 응답 (200 또는 302 리다이렉트)
    assert response.status_code in (200, 302), f"예상치 못한 상태 코드: {response.status_code}"
