"""Python 구문 검증 테스트 - 라인 넘버 오염 방지"""
import compileall
import sys
import tempfile
from pathlib import Path


def test_app_syntax():
    """app/ 디렉토리의 모든 Python 파일이 유효한 구문인지 검증"""
    result = compileall.compile_dir(
        "app",
        quiet=1,  # 오류만 출력
        force=True,
        ddir="app",
    )
    assert result, "app/ 디렉토리에 구문 오류가 있는 파일이 있습니다"


def test_migrations_syntax():
    """migrations/ 디렉토리의 모든 Python 파일이 유효한 구문인지 검증"""
    result = compileall.compile_dir(
        "migrations",
        quiet=1,
        force=True,
        ddir="migrations",
    )
    assert result, "migrations/ 디렉토리에 구문 오류가 있는 파일이 있습니다"


def test_tests_syntax():
    """tests/ 디렉토리의 모든 Python 파일이 유효한 구문인지 검증"""
    result = compileall.compile_dir(
        "tests",
        quiet=1,
        force=True,
        ddir="tests",
    )
    assert result, "tests/ 디렉토리에 구문 오류가 있는 파일이 있습니다"


def test_no_line_number_corruption():
    """
    라인 넘버 오염 감지 (예: '    10|', '   100|' 같은 패턴)
    
    이 버그는 Read 도구의 라인 넘버가 실제 소스 코드에 들어가는 경우 발생.
    Python 파일에 이런 패턴이 있으면 SyntaxError가 발생.
    """
    import re
    
    # 라인 넘버 패턴: 공백 + 숫자 + 파이프 (예: "    10|", "   100|")
    line_number_pattern = re.compile(r'^\s+\d+\|', re.MULTILINE)
    
    corruption_found = []
    
    # app/, migrations/, tests/ 검사
    for directory in ["app", "migrations", "tests"]:
        path = Path(directory)
        if not path.exists():
            continue
            
        for py_file in path.rglob("*.py"):
            if "__pycache__" in str(py_file):
                continue
                
            try:
                content = py_file.read_text(encoding="utf-8")
                matches = line_number_pattern.findall(content)
                
                if matches:
                    corruption_found.append(f"{py_file}: {len(matches)} 라인 넘버 오염 발견")
            except Exception as e:
                # 읽기 오류는 무시 (바이너리 파일 등)
                pass
    
    assert not corruption_found, (
        f"라인 넘버 오염이 발견되었습니다:\n" + "\n".join(corruption_found) +
        "\n\n이 파일들은 Read 도구의 라인 넘버가 실제 코드에 포함된 것입니다. "
        "파일을 재생성하거나 sed/정규식으로 '    숫자|' 패턴을 제거하세요."
    )
