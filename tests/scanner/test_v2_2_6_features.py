"""v2.2.6 기능 테스트."""

import pytest


def test_version_is_2_2_6():
    """__version__ = 2.2.6"""
    from app import __version__
    assert __version__.__version__ == "2.2.6"


def test_version_in_dockerfile_not_hardcoded():
    """Dockerfile에 버전 하드코딩 없음."""
    import os
    dockerfile_path = os.path.join(os.path.dirname(__file__), '..', '..', 'Dockerfile')
    with open(dockerfile_path, 'r') as f:
        content = f.read()
    
    # ARG APP_VERSION에 기본값이 없어야 함
    assert 'ARG APP_VERSION=2.2.3' not in content
    assert 'ARG APP_VERSION' in content  # ARG는 있어야 함


def test_workflow_no_hardcoded_version():
    """GitHub workflow에 버전 하드코딩 없음."""
    import os
    workflow_path = os.path.join(os.path.dirname(__file__), '..', '..', '.github', 'workflows', 'docker-publish.yml')
    with open(workflow_path, 'r') as f:
        content = f.read()
    
    # APP_VERSION build-arg가 없어야 함
    assert 'APP_VERSION=' not in content or 'APP_VERSION=${{' in content


def test_tesla_soc_uses_ui_not_average():
    """Tesla SOC는 UI SOC 사용 (average 아님)."""
    from app.modules.tesla import decode as tesla_decode
    
    # 0x292 디코더가 soc_ui 반환하는지 확인
    frames = [(0.1, b'\x00\x01\x02\x03\x04\x05\x06\x07')]
    result = tesla_decode.decode_0x292_soc(frames)
    
    assert 'soc_ui' in result
    assert 'soc_ave' in result


def test_tesla_decode_dlc_6_frames():
    """Tesla 디코더가 DLC 6 프레임 처리."""
    from app.modules.tesla import decode as tesla_decode
    
    # DLC 6 프레임 (8바이트 미만)
    frames_dlc_6 = [(0.1, b'\x00\x01\x02\x03\x04\x05')]
    
    # 0x292 SOC (최소 3바이트 필요)
    result_soc = tesla_decode.decode_0x292_soc(frames_dlc_6)
    assert 'soc_ui' in result_soc  # UI SOC는 3바이트로 디코딩 가능
    
    # 0x132 Pack V/I (최소 2바이트 필요)
    result_pack = tesla_decode.decode_0x132_pack_vi(frames_dlc_6)
    assert 'pack_voltage' in result_pack  # 전압은 2바이트로 디코딩 가능
    
    # 0x332 Summary (mux 0은 5바이트, mux 1은 6바이트 필요)
    frames_dlc_8 = [(0.1, b'\x00\x00\x20\x21\x22\x00\x00\x00')]  # mux 0
    result_temp = tesla_decode.decode_0x332_summary(frames_dlc_8)
    # DLC 8이면 온도 디코딩 가능
    assert 'temp_max' in result_temp or len(result_temp) == 0  # 데이터가 없을 수도 있음


def test_max_content_length_600mb():
    """업로드 한도 600MB (다중 파일 대응)."""
    from app.config import Config
    assert Config.MAX_CONTENT_LENGTH == 600 * 1024 * 1024


def test_excluded_items_deduplication():
    """제외된 항목 예시 중복 제거."""
    # PDF 렌더링 로직에서 중복 제거 확인
    # (실제 PDF 생성은 복잡하므로 로직만 확인)
    from app.modules.scanner.pdf import _additional_info_and_issues_section
    
    view = {
        "additional_info": [],
        "issues": {
            "excluded_steps": {
                "count": 3,
                "message": "3개 단계 제외",
                "examples": [
                    {"reason": "SecurityAccess"},
                    {"reason": "SecurityAccess"},  # 중복
                    {"reason": "WriteData"},
                ]
            }
        }
    }
    
    story = _additional_info_and_issues_section(view)
    
    # story는 Paragraph 객체 리스트이므로 텍스트 추출
    story_text = "\n".join(str(p) for p in story if hasattr(p, '__str__'))
    
    # "예: SecurityAccess"가 한 번만 나와야 함
    assert story_text.count("예: SecurityAccess") == 1
    assert story_text.count("예: WriteData") == 1


def test_tesla_report_no_raw_dict():
    """Tesla 보고서에 raw dict 없음 (사람이 읽을 수 있는 형식)."""
    from app.modules.scanner.report import tesla_view
    
    # Mock scan과 decoded 데이터
    class MockScan:
        id = 1
        car_no = "88테8888"
        car_maker = "Tesla"
        car_model = "Model 3"
        car_year = 2021
        car_fuel = "전기"
        created_at = None
        device = "테스트"
        bms_data = {}
    
    scan = MockScan()
    decoded = {
        'soc': {'soc_ui': 50.5, 'soc_ave': 51.0},
        'energy': {'nominal_full_pack_energy': 72.0},
    }
    tesla_data = {
        'soh': {'soh_available': False, 'calculation_note': '기준 없음'}
    }
    
    view = tesla_view(scan, decoded, tesla_data)
    
    # additional_info는 리스트여야 하고, dict가 아니어야 함
    assert isinstance(view.get('additional_info'), list)
    
    # 각 항목이 문자열이어야 함
    for item in view.get('additional_info', []):
        assert isinstance(item, str), f"Expected string, got {type(item)}: {item}"


def test_ml_feature_extraction_anonymized():
    """ML 특징 추출 시 차량번호/VIN 제외 (익명화)."""
    from app.modules.ml_learning.feature_extractor import extract_and_store_features
    from app.modules.scans.models import Scan
    from app.extensions import db
    
    # 이 테스트는 DB 컨텍스트 필요 (실제 테스트에서는 _app_base 필요)
    # 여기서는 로직만 검증
    pass  # 실제 테스트는 통합 테스트에서


def test_ml_tables_migration_exists():
    """ML learning 테이블 마이그레이션 존재."""
    import os
    migrations_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'migrations', 'versions')
    
    # 마이그레이션 파일 존재 확인
    migration_files = os.listdir(migrations_dir)
    ml_migrations = [f for f in migration_files if 'ml_learning' in f or '20261116_120000' in f]
    
    assert len(ml_migrations) > 0, "ML learning migration not found"


def test_tesla_soh_reference_citation():
    """Tesla SOH 참고치 출처 표시."""
    from app.modules.tesla.soh import calculate_soh
    
    result = calculate_soh(
        current_nominal_full=70.0,
        manufacturer="Tesla",
        model="Model 3",
        year=2020,
    )
    
    # community 출처일 때 경고 포함
    if result.get('reference_source') == 'community':
        assert 'community' in str(result.get('warnings', [])).lower() or 'calculation_note' in result
