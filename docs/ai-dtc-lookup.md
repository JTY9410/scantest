# AI 기반 고장코드 조회

## 개요

knowledge_dtcs에 없거나 초안(draft)만 있는 DTC를 AI로 조회하고 캐시합니다.

## 설정

### 환경변수 (.env)

```bash
# AI DTC 조회 (선택). 없으면 '미확인(AI 조회 불가)'로 표시되고 스캔은 정상 진행.
OPENAI_API_KEY=sk-...
AI_DTC_PROVIDER=openai
AI_DTC_MODEL=gpt-4o-mini
AI_DTC_TIMEOUT=10
```

## 동작 방식

### 1. DTC 조회 우선순위

`app/modules/knowledge/service.py:lookup_dtcs()`:

1. **검증된 DTC 우선**: `status='verified'` 레코드 검색
2. **AI 조회**: 없으면 AI 호출
3. **캐시 저장**: `source='ai'`, `status='draft'`, `confidence=0.6`

### 2. AI 조회 입력

- `code`: DTC 코드 (예: P0420)
- `maker`: 제조사 (예: 현대, 기아)
- `model`: 차종 (예: 아이오닉5, EV6)
- `year`: 연식
- `ecu`: ECU 주소 (16진수)

**Privacy 보장**: VIN·차량번호는 AI에 전송하지 않음.

### 3. AI 응답 형식

```python
{
    "description": "한글 설명",
    "subsystem": "계통",
    "severity": "심각도 (주의/경고/심각)",
    "rationale": "근거/출처"
}
```

### 4. 데이터베이스 저장

```python
KnowledgeDTC(
    code="P0420",
    maker="현대",
    description="촉매 효율 저하",
    subsystem="배기",
    severity="주의",
    notes="AI 추정: 표준 OBD-II 규격",
    source="ai",
    source_detail="openai:gpt-4o-mini",
    confidence=0.6,
    status="draft"
)
```

### 5. 보고서 표시

- **HTML**: 'AI 추정(미검증)' 배지 (노란색 경고)
- **PDF**: (TODO - 현재 미구현)

## 격리 및 안정성

### 완전 격리

AI 호출 실패가 스캔 저장을 막지 않음:

```python
try:
    ai_dtc = lookup_and_cache_dtc(code, maker, model, year, ecu)
except Exception as exc:
    current_app.logger.warning(f"AI DTC lookup failed: {exc}")
    # 스캔 저장은 계속 진행
```

### IntegrityError 처리

동시 요청이 같은 DTC를 생성하면:

```python
try:
    db.session.commit()
except IntegrityError:
    db.session.rollback()
    return existing_record
```

## 검증 워크플로우

1. **AI 추정**: `status='draft'`, 배지 표시
2. **관리자 검토**: 지식 베이스 관리 화면에서 확인
3. **검증 완료**: `status='verified'`로 변경
4. **우선순위**: 검증된 DTC가 AI 추정보다 우선

## 테스트

### Mock 기반 테스트

`tests/knowledge/test_ai_dtc.py`:

- API 키 없을 때 동작
- AI 조회 성공
- 검증된 DTC 캐시 우선
- AI 호출 실패 격리
- 동시 요청 중복 처리

**실제 API 호출 없음** (Mock 사용).

## 비용 및 제한

- **모델**: gpt-4o-mini (저비용)
- **타임아웃**: 10초 (설정 가능)
- **캐시**: 같은 `code+maker` 조합은 1회만 조회
- **선택 사항**: API 키 없으면 스캔은 정상 진행

## TODO

- [ ] PDF 보고서에 AI 배지 추가
- [ ] 관리자 화면에서 AI 추정 일괄 검토
- [ ] AI 조회 통계 (성공/실패/캐시 히트)
- [ ] 다중 AI 프로바이더 지원 (Anthropic, Gemini)
