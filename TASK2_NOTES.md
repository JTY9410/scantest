# Task 2 완료 및 미해결 이슈

## ✅ 완료

### Learning Persistence
- `command_stats` 테이블: maker/model/ecu/command별 성공/실패/타임아웃/NRC 추적
- `learning_runs` 테이블: 실험 추적 (candidate/promoted/rolled_back)
- `continuous_learning.py`: 
  - `persist_to_database()`: command_stats에 저장, UCB score 계산
  - `load_from_database()`: DB에서 로드
  - `select_commands_ucb()`: UCB 알고리즘으로 top-k 명령 선택
- Thompson sampling 파라미터 (alpha/beta) command_stats에 저장

### CLI Commands
- `flask learning stats [--maker] [--model] [--ecu] [--limit]`: 학습 통계 조회
- `flask learning promote <run_id> [--yes]`: 실험 승격
- `flask learning rollback <run_id> --reason <text> [--yes]`: 롤백

### Admin Page
- `/admin/learning`: 학습 현황 대시보드
  - 전체 통계 (제조사/모델/ECU/명령 개수, 총 시도, 성공률)
  - 제조사별 통계
  - 학습 실행 기록
  - Top 20 명령 (UCB Score 순)

## ⚠️ 미해결 이슈

### 1. Category 백필 0건
**원인**: `ecu_backfill.py`의 category 추출 로직이 너무 제한적
- 현재: DBC comment에 category 키워드가 있거나, file path에 category가 있을 때만
- 문제: 대부분 DBC 파일의 comment에는 category 키워드가 없음

**해결방안** (사용자 지시대로 명시적 근거만 사용):
1. **CanZE 필드 파일**: CSV에 category 열이 있는지 확인 필요
   - `importers.py` line 463-503에서 CanZE CSV 파싱
   - 현재는 category 열을 읽지 않음
   - CanZE CSV 실제 구조 확인 후 category 열 인덱스 파악 필요
   
2. **DBC 속성**: DBC 파일에 signal attributes로 category 정의 여부
   - `BA_ "Category" SG_ ...` 형식
   - 현재 DBC 파서가 attributes를 읽는지 확인 필요

### 2. CanZE 명령 이름 파싱 오류
**증상**: 리포트에서 'ff', '4ff' 같은 hex 값이 이름으로 나타남

**원인**: `importers.py` line 471
```python
field_name = row[10] if len(row) > 10 else ''
```
- Column 10이 field name이 아니라 hex 값일 가능성
- CanZE CSV의 실제 컬럼 구조 확인 필요

**해결방안**:
1. 실제 CanZE CSV 파일 샘플 확인
2. 정확한 컬럼 인덱스 파악 (name/description이 어느 컬럼인지)
3. `importers.py`의 `import_canze_csv()` 수정

## 권장 조치

### CanZE CSV 구조 확인
```bash
# 맥에서 CanZE 파일 샘플 확인
find /path/to/definitions -name "*.csv" -path "*/CanZE/*" | head -1 | xargs head -5
```

### DBC Attributes 확인
```bash
# DBC 파일에 BA_ attributes 있는지 확인
grep -h "^BA_" /path/to/definitions/*.dbc | head -20
```

## 통합 테스트
Task 2 통합 테스트는 시간 제약으로 미완성. 추가 필요:
- `tests/scanner/test_learning_persistence.py`
- `tests/cli/test_learning_cli.py`
- `tests/admin/test_learning_admin_views.py`
