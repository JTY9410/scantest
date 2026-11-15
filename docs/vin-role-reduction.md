# VIN 조회 역할 축소

## 개요

VIN 디코딩 결과는 **참고자료**로만 사용하고, 차량번호 조회가 **1차 기준**입니다.

## 현재 문제 (Before)

```python
# VIN 결과가 차량번호 결과를 덮어씀
if vin_result:
    car["diag_company"] = vin_result["maker"]  # ❌ 차량번호 결과 손실
    car["diag_model"] = vin_result["model"]
```

## 개선 방향 (After)

### 1. 우선순위

1. **차량번호 조회**: 제조사, 차종, 연식, 동력원의 1차 기준
2. **VIN 디코딩**: 참고 정보로만 사용
3. **불일치 감지**: 차량번호 vs VIN 차이를 문제점 섹션에 표시

### 2. 데이터 흐름

```
차량번호 조회 ──┐
                ├─→ 차량 정보 (1차)
VIN 디코딩 ─────┘    ↓
                   불일치 확인
                     ↓
                   문제점 기록
```

### 3. 구현 계획

#### app/modules/scanner/service.py

```python
def run_scan(actor, *, car_no, car, steps, transport, **kwargs):
    # 1. 차량번호 조회 (기존)
    plate_info = car_info.lookup(car_no) if car_no else None
    
    # 2. VIN 디코딩 (스캔 결과에서)
    result, trace = interpret(steps, ...)
    vin = result.get("vin")
    vin_info = decode_vin(vin) if vin else None
    
    # 3. 우선순위 적용
    primary = plate_info or {}  # 차량번호가 1차
    
    if vin_info:
        # VIN은 참고로만
        result["vin_info_reference"] = vin_info
        
        # 불일치 감지
        conflicts = detect_conflicts(primary, vin_info)
        if conflicts:
            _add_error(result, "info_mismatch", "차량정보 불일치", 
                      "warning", f"번호판 조회 vs VIN 불일치: {conflicts}")
    
    # 4. 차량번호 없을 때만 VIN 사용
    if not plate_info and vin_info:
        result["using_vin_fallback"] = True
        car.update(vin_info)  # '참고(VIN)'로 표시
```

#### 불일치 감지 함수

```python
def detect_conflicts(plate_info: dict, vin_info: dict) -> list[str]:
    """차량번호 vs VIN 불일치 항목."""
    conflicts = []
    
    # 제조사
    if plate_info.get("maker") != vin_info.get("maker"):
        conflicts.append(f"제조사: {plate_info.get('maker')} vs {vin_info.get('maker')}")
    
    # 차종
    if plate_info.get("model") != vin_info.get("model"):
        conflicts.append(f"차종: {plate_info.get('model')} vs {vin_info.get('model')}")
    
    # 연료
    if plate_info.get("fuel") != vin_info.get("fuel"):
        conflicts.append(f"연료: {plate_info.get('fuel')} vs {vin_info.get('fuel')}")
    
    return conflicts
```

### 4. 화면 표시

#### 보고서 헤더

```html
<!-- 차량번호 있을 때: 1차 정보 표시 -->
<p>제조사: {{ view.maker }}</p>
<p>차종: {{ view.model }}</p>

{% if view.vin_fallback %}
  <span class="badge badge-info">참고(VIN)</span>
{% endif %}

<!-- VIN 불일치 경고 -->
{% if view.vin_conflicts %}
  <div class="alert alert-warning">
    <strong>⚠️ 차량정보 불일치</strong>
    <ul>
      {% for conflict in view.vin_conflicts %}
        <li>{{ conflict }}</li>
      {% endfor %}
    </ul>
  </div>
{% endif %}
```

#### 문제점 섹션

```html
{% if view.vin_conflicts %}
  <h3>차량정보 불일치</h3>
  <table>
    <tr><th>항목</th><th>차량번호 조회</th><th>VIN 디코딩</th></tr>
    {% for item in view.vin_conflicts %}
      <tr>
        <td>{{ item.field }}</td>
        <td>{{ item.plate_value }}</td>
        <td>{{ item.vin_value }}</td>
      </tr>
    {% endfor %}
  </table>
  <p class="text-muted">차량번호 조회 결과를 기준으로 판정했습니다.</p>
{% endif %}
```

### 5. 충돌 모달 통합

기존 충돌 모달(`components/powertrain_conflict_modal.html`)에 VIN 불일치도 추가:

```html
{% if view.has_vin_conflict %}
  <div class="conflict-item">
    <h4>VIN 불일치</h4>
    <p>차량번호: {{ view.plate_info.maker }} {{ view.plate_info.model }}</p>
    <p>VIN 디코딩: {{ view.vin_info.maker }} {{ view.vin_info.model }}</p>
    <button onclick="useVin()">VIN 기준 적용</button>
  </div>
{% endif %}
```

## 마이그레이션

### DB 스키마 변경 (선택)

```sql
-- inspections 테이블에 VIN 참고 정보 컬럼 추가
ALTER TABLE inspections ADD COLUMN vin_info_json JSONB;
ALTER TABLE inspections ADD COLUMN using_vin_fallback BOOLEAN DEFAULT FALSE;

-- 불일치 기록
ALTER TABLE inspections ADD COLUMN info_conflicts TEXT[];
```

### 기존 스캔 호환성

- 기존 스캔은 그대로 유지
- 새 스캔부터 우선순위 적용

## 테스트

### 시나리오 1: 차량번호 있음 + VIN 일치

```python
def test_plate_and_vin_match():
    plate = {"maker": "현대", "model": "아이오닉5"}
    vin = "KMHEV6..."  # VIN also decodes to 현대 아이오닉5
    
    scan = run_scan(..., car_no="12가3456", steps=...)
    
    assert scan.maker == "현대"
    assert scan.model == "아이오닉5"
    assert not scan.has_conflicts
```

### 시나리오 2: 차량번호 있음 + VIN 불일치

```python
def test_plate_and_vin_mismatch():
    plate = {"maker": "현대", "model": "아이오닉5"}
    vin = "KNAC5..."  # VIN decodes to 기아 EV6
    
    scan = run_scan(..., car_no="12가3456", steps=...)
    
    # 차량번호 우선
    assert scan.maker == "현대"
    assert scan.model == "아이오닉5"
    
    # 불일치 기록
    assert scan.has_conflicts
    assert "제조사" in scan.conflicts[0]
```

### 시나리오 3: 차량번호 없음 + VIN만

```python
def test_no_plate_vin_only():
    vin = "KMHEV6..."  # 현대 아이오닉5
    
    scan = run_scan(..., car_no=None, steps=...)
    
    # VIN 참고 사용
    assert scan.maker == "현대"
    assert scan.using_vin_fallback
    assert "참고(VIN)" in scan.view_data
```

## 참고

- `app/modules/scans/car_info.py`: 차량번호 조회
- `app/modules/utils/vin_decoder.py`: VIN 디코딩
- `app/modules/scanner/report.py`: 보고서 생성
- `app/templates/scanner/inspection.html`: 보고서 화면

## TODO

- [ ] detect_conflicts() 구현
- [ ] run_scan() 우선순위 로직 적용
- [ ] 보고서 템플릿 수정
- [ ] 충돌 모달 통합
- [ ] 테스트 작성
- [ ] 기존 스캔 마이그레이션 (선택)
