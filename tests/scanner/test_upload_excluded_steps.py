"""업로드 시 SecurityAccess 등 제외된 단계 처리 테스트."""

import pytest
from io import BytesIO
from werkzeug.datastructures import FileStorage


def test_upload_excludes_security_access_and_write_commands(_app_base, make_user):
    """
    SecurityAccess(0x27), WriteData(0x2E) 등 제외 대상 명령이 포함된 로그 업로드.
    
    - SecurityAccess: 시드/키가 8바이트 초과
    - WriteDataByIdentifier: 쓰기 명령
    - 10 01/10 03 반복, 3E 80
    - 7DF 브로드캐스트 다중 응답
    - 업로드 200 → Scan 생성 → PDF 생성 가능
    """
    from app.modules.scanner.upload import process_upload
    from app.modules.scans.models import Scan
    from app.modules.scanner.service import scan_document
    from app.extensions import db
    import pypdf
    
    with _app_base.app_context():
        admin_id = make_user(tid="exclude_steps_admin", type="admin")
        
        # 가짜 로그: SecurityAccess, WriteData, 반복 명령, 브로드캐스트
        csv_lines = ["Timestamp,Channel,CAN_ID,DLC,Data"]
        t = 0.0
        
        # 1. 세션 제어 (반복)
        for i in range(5):
            csv_lines.append(f"{t:.6f},Tx,0x7E4,8,02 10 01 00 00 00 00 00")
            csv_lines.append(f"{t+0.01:.6f},Rx,0x7EC,8,06 50 01 00 32 01 F4 00")
            t += 0.05
        
        # 2. SecurityAccess (8바이트 초과 - 시드 10바이트)
        csv_lines.append(f"{t:.6f},Tx,0x5D0,8,02 27 41 00 00 00 00 00")
        csv_lines.append(f"{t+0.01:.6f},Rx,0x5D8,8,10 14 67 41 01 23 45 67")
        csv_lines.append(f"{t+0.02:.6f},Rx,0x5D8,8,21 89 AB CD EF 12 34 56")
        csv_lines.append(f"{t+0.03:.6f},Rx,0x5D8,8,22 78 9A BC DE 00 00 00")
        t += 0.1
        
        # 3. SecurityAccess - 키 전송 (8바이트 초과)
        csv_lines.append(f"{t:.6f},Tx,0x5D0,8,10 0C 27 42 92 BF 3A 5C")
        csv_lines.append(f"{t+0.01:.6f},Tx,0x5D0,8,21 7D 8E 9F A1 B2 00 00")
        csv_lines.append(f"{t+0.02:.6f},Rx,0x5D8,8,02 67 42 00 00 00 00 00")
        t += 0.1
        
        # 4. WriteDataByIdentifier (쓰기 명령)
        csv_lines.append(f"{t:.6f},Tx,0x7E4,8,05 2E F1 90 01 02 00 00")
        csv_lines.append(f"{t+0.01:.6f},Rx,0x7EC,8,03 6E F1 90 00 00 00 00")
        t += 0.05
        
        # 5. Tester Present (반복)
        for i in range(10):
            csv_lines.append(f"{t:.6f},Tx,0x7E4,8,02 3E 80 00 00 00 00 00")
            t += 0.05
        
        # 6. 브로드캐스트 (7DF → 다중 ECU 응답)
        for i in range(3):
            csv_lines.append(f"{t:.6f},Tx,0x7DF,8,02 01 00 00 00 00 00 00")
            csv_lines.append(f"{t+0.01:.6f},Rx,0x598,8,06 41 00 BE 3E B8 11 00")
            csv_lines.append(f"{t+0.015:.6f},Rx,0x59E,8,06 41 00 BE 3E B8 11 00")
            csv_lines.append(f"{t+0.020:.6f},Rx,0x788,8,06 41 00 BE 3E B8 11 00")
            t += 0.1
        
        # 7. 정상 DTC 읽기
        csv_lines.append(f"{t:.6f},Tx,0x7E4,8,01 03 00 00 00 00 00 00")
        csv_lines.append(f"{t+0.01:.6f},Rx,0x7EC,8,02 43 00 00 00 00 00 00")
        
        csv_content = "\n".join(csv_lines)
        
        file = FileStorage(
            stream=BytesIO(csv_content.encode()),
            filename="ev9_security_access.csv",
            content_type="text/csv"
        )
        
        # Upload and process
        scan_id = process_upload(
            actor=admin_id,
            file=file,
            car_no="88가8888",
            device="EV9 SecurityAccess Test"
        )
        
        assert scan_id is not None
        scan = db.session.get(Scan, scan_id)
        assert scan is not None
        
        # 검증 1: 제외된 단계 기록 확인 (bms_data.upload_metadata에 저장됨)
        assert scan.bms_data is not None
        metadata = scan.bms_data.get('upload_metadata')
        assert metadata is not None, "upload_metadata 누락"
        assert metadata['excluded_steps_count'] > 0, "제외된 단계가 기록되지 않음"
        
        # SecurityAccess(0x27)와 WriteData(0x2E)가 제외되었는지 확인
        excluded = metadata.get('excluded_steps', [])
        assert any('27' in ex['command'] for ex in excluded), "SecurityAccess가 제외되지 않음"
        assert metadata['excluded_steps_count'] >= 3, f"제외 건수 부족: {metadata['excluded_steps_count']}"
        
        # 검증 2: Scan이 정상 생성됨 (400 에러 없음)
        assert scan.type in ('ev', 'hev', 'ice')
        
        # 검증 3: PDF 생성 가능
        document = scan_document(scan)
        assert document is not None
        assert document.content.startswith(b"%PDF")
        
        # 검증 4: PDF에 제외된 단계 정보 포함
        reader = pypdf.PdfReader(BytesIO(document.content))
        full_text = ""
        for page in reader.pages:
            full_text += page.extract_text()
        
        # '추가 수집 정보와 문제점' 또는 '제외' 관련 텍스트 확인
        assert "제외" in full_text or "SecurityAccess" in full_text or "단계" in full_text, \
            "PDF에 제외된 단계 정보가 없습니다"
        
        db.session.rollback()


def test_convert_to_scan_steps_filters_security_access():
    """convert_to_scan_steps가 SecurityAccess를 필터링하는지 직접 검증."""
    from app.modules.scanner.upload import convert_to_scan_steps
    
    # SecurityAccess가 포함된 간단한 trace
    trace_text = """Timestamp,Channel,CAN_ID,DLC,Data
0.000000,Tx,0x7E4,8,02 10 01 00 00 00 00 00
0.010000,Rx,0x7EC,8,06 50 01 00 32 01 F4 00
0.050000,Tx,0x5D0,8,02 27 41 00 00 00 00 00
0.060000,Rx,0x5D8,8,10 14 67 41 01 23 45 67 89
0.070000,Rx,0x5D8,8,21 AB CD EF 12 34 56 78 9A
0.100000,Tx,0x7E4,8,01 03 00 00 00 00 00 00
0.110000,Rx,0x7EC,8,02 43 00 00 00 00 00 00
"""
    
    steps, metadata = convert_to_scan_steps(trace_text)
    
    # SecurityAccess (0x27)가 제외되었는지 확인
    assert metadata['excluded_steps_count'] > 0
    excluded_cmds = [ex['command'] for ex in metadata.get('excluded_steps', [])]
    assert any('27 41' in cmd for cmd in excluded_cmds), "SecurityAccess 0x27 41이 제외되지 않음"
    
    # 남은 steps에는 10 01과 03만 있어야 함
    commands = [step['command'] for step in steps]
    assert any('10 01' in cmd for cmd in commands), "10 01이 누락됨"
    assert any('03' in cmd for cmd in commands), "03이 누락됨"
    assert not any('27' in cmd for cmd in commands), "SecurityAccess가 여전히 steps에 포함됨"
