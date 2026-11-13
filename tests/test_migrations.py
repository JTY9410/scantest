"""Alembic 마이그레이션 검증 테스트"""
import os
from pathlib import Path


def test_single_alembic_head():
    """
    Alembic 마이그레이션 그래프에 정확히 하나의 헤드만 존재하는지 검증.
    
    다중 헤드가 있으면 'flask db upgrade' 실행 시 오류 발생:
    ERROR [flask_migrate] Error: Multiple head revisions are present for given argument 'head'
    """
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    
    # Alembic 설정 파일 경로
    migrations_dir = Path(__file__).parent.parent / "migrations"
    alembic_ini = migrations_dir / "alembic.ini"
    
    assert alembic_ini.exists(), f"Alembic 설정 파일을 찾을 수 없습니다: {alembic_ini}"
    
    # ScriptDirectory 생성
    config = Config(str(alembic_ini))
    config.set_main_option("script_location", str(migrations_dir))
    script_directory = ScriptDirectory.from_config(config)
    
    # 현재 헤드들 확인
    heads = script_directory.get_heads()
    
    assert len(heads) == 1, (
        f"Alembic 마이그레이션 그래프에 {len(heads)}개의 헤드가 있습니다: {heads}\n"
        f"정확히 1개의 헤드만 있어야 합니다.\n"
        f"다중 헤드가 있으면 컨테이너 시작 시 'flask db upgrade'가 실패합니다.\n"
        f"해결 방법:\n"
        f"1. 각 마이그레이션 파일의 down_revision을 확인하여 올바른 부모를 가리키도록 수정\n"
        f"2. 또는 'flask db merge'로 병합 마이그레이션 생성"
    )
