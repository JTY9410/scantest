#!/bin/bash
# 전체 테스트 실행 스크립트

set -e

echo "=== WecarScan 전체 테스트 실행 ==="
echo ""

# Python 버전 확인
echo "Python 버전:"
python3 --version || python --version
echo ""

# 현재 디렉토리
echo "작업 디렉토리: $(pwd)"
echo ""

# 가상 환경 확인
if [ -d "venv" ]; then
    echo "가상 환경 활성화..."
    source venv/bin/activate
fi

# 의존성 설치 여부 확인
echo "설치된 패키지 확인..."
pip list | grep -E "(Flask|pytest)" || {
    echo "의존성이 설치되지 않았습니다."
    echo "다음 명령으로 설치하세요:"
    echo "  pip install -r requirements.lock -r requirements-dev.lock"
    exit 1
}
echo ""

# pytest 실행
echo "=== Python 테스트 (pytest) ==="
python -m pytest tests/scanner/test_transport.py -v --tb=short
echo ""

echo "=== Python 기존 테스트 (scanner) ==="
python -m pytest tests/scanner/test_ethernet.py -v --tb=short
echo ""

# Node.js 테스트
if command -v node &> /dev/null; then
    echo "=== JavaScript 테스트 (node) ==="
    if [ -f "tests/js/test_sample.js" ]; then
        node --test tests/js/*.test.js
    else
        echo "JavaScript 테스트 파일이 없습니다. 건너뜁니다."
    fi
    echo ""
else
    echo "Node.js가 설치되지 않았습니다. JavaScript 테스트를 건너뜁니다."
    echo ""
fi

echo "=== 테스트 완료 ==="
