# 차종 수동 지정 및 재해석

## 개요

VIN으로 제조사·연식만 판별되고 모델이 미확인일 때, 관리자가 차종을 수동 지정하면 해당 차종 정의를 적용해 스캔 결과를 재해석합니다.

## 사용 시나리오

### Before (현재)

```
VIN: KMHEV6D1XRA123456
└─ 제조사: 현대
└─ 연식: 2024
└─ 모델: 미확인 ❌
└─ 결과: 기본 해석 (셀 수, 배터리 용량 등 미적용)
```

### After (구현 후)

```
VIN: KMHEV6D1XRA123456
└─ 제조사: 현대
└─ 연식: 2024
└─ 모델: 관리자 지정 → 아이오닉5 ✅
└─ 결과: 아이오닉5 정의 적용 (셀 192개, 77.4 kWh)
```

## 구현 계획

### 1. DB 스키마

#### 기존 테이블 활용

`inspections` 테이블에 `manual_model_id` 추가:

```sql
ALTER TABLE inspections ADD COLUMN manual_model_id INTEGER;
ALTER TABLE inspections ADD FOREIGN KEY (manual_model_id) 
    REFERENCES vehicle_definitions(id) ON DELETE SET NULL;
```

#### VehicleDefinition (기존)

```python
# app/modules/definitions/models.py
class VehicleDefinition(db.Model):
    id: int
    maker: str
    model: str
    submodel: str | None
    year_from: int | None
    year_to: int | None
    powertrain: str  # BEV|PHEV|HEV|ICE
    battery_spec_id: int | None  # FK to battery_specs
    notes: str | None
```

### 2. API 엔드포인트

#### 차종 검색

```http
GET /admin/vehicle-definitions?maker=기아&model=EV9&year=2024

Response:
[
  {
    "id": 123,
    "maker": "기아",
    "model": "EV9",
    "submodel": "AWD",
    "year_from": 2023,
    "year_to": 2024,
    "powertrain": "BEV",
    "battery_spec": {
      "capacity_kwh": 99.8,
      "cell_count": 288
    }
  }
]
```

#### 차종 지정 및 재해석

```http
POST /scanner/inspections/<id>/set-model

Request:
{
  "vehicle_definition_id": 123
}

Response:
{
  "success": true,
  "inspection_id": 456,
  "model_applied": "기아 EV9",
  "reinterpreted": true,
  "changes": {
    "battery_cells": { "before": null, "after": 288 },
    "capacity_kwh": { "before": null, "after": 99.8 },
    "judgments": { ... }
  }
}
```

### 3. 재해석 로직

```python
def reinterpret_with_model(inspection_id: int, vehicle_definition_id: int):
    """차종 정의를 적용해 스캔 결과 재해석."""
    
    inspection = Inspection.query.get_or_404(inspection_id)
    vehicle_def = VehicleDefinition.query.get_or_404(vehicle_definition_id)
    
    # 1. manual_model_id 저장
    inspection.manual_model_id = vehicle_definition_id
    
    # 2. 차종 정의로 result JSON 재계산
    result = json.loads(inspection.result)
    car_info = {
        "maker": vehicle_def.maker,
        "model": vehicle_def.model,
        "year": vehicle_def.year_from,
        "powertrain": vehicle_def.powertrain,
        "battery_spec_id": vehicle_def.battery_spec_id
    }
    
    # 3. 재해석 (배터리 셀, SOH, 판정 등)
    reinterpreted = apply_vehicle_rules(result, car_info)
    inspection.result = json.dumps(reinterpreted)
    
    # 4. 종합 판정 재계산
    inspection.overall_judgment = calculate_overall_judgment(reinterpreted)
    
    db.session.commit()
    return inspection
```

### 4. UI 구현

#### 스캔 상세 페이지

```html
<!-- templates/scanner/inspection.html -->

{% if not view.model or view.model == "미확인" %}
<div class="alert alert-warning">
  <p>차종이 확인되지 않았습니다. 차종을 지정하면 더 정확한 판정을 받을 수 있습니다.</p>
  <button onclick="openModelSelector()">차종 지정</button>
</div>
{% endif %}

{% if view.manual_model %}
<div class="alert alert-info">
  <p>관리자 지정 차종: <strong>{{ view.manual_model }}</strong></p>
  <button onclick="removeModel()">지정 해제</button>
</div>
{% endif %}
```

#### 차종 선택 모달

```javascript
function openModelSelector() {
  // AJAX로 차종 목록 조회
  fetch(`/admin/vehicle-definitions?maker=${maker}&year=${year}`)
    .then(res => res.json())
    .then(vehicles => {
      // 모달에 차종 목록 표시
      showModal(vehicles);
    });
}

function setModel(definitionId) {
  fetch(`/scanner/inspections/${inspectionId}/set-model`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ vehicle_definition_id: definitionId })
  })
  .then(res => res.json())
  .then(data => {
    if (data.success) {
      location.reload();  // 재해석 완료 후 새로고침
    }
  });
}
```

## 차종 정의: 기아 EV9

### 공식 스펙 (출처 필수)

```python
# seeds/kia_ev9.py
{
    "maker": "기아",
    "model": "EV9",
    "submodel": "AWD",  # 또는 "2WD"
    "year_from": 2023,
    "year_to": 2024,
    "powertrain": "BEV",
    "battery_spec": {
        "capacity_kwh": 99.8,  # 출처: https://www.kia.com/kr/vehicles/ev9/specification
        "cell_count": None,    # 공식 자료 미공개 (추후 업데이트)
        "module_count": None,  # 공식 자료 미공개
        "nominal_voltage": None,  # 공식 자료 미공개
        "cell_chemistry": "NCM"  # 추정 (공식 확인 필요)
    },
    "notes": "출처: 기아 공식 웹사이트 (https://www.kia.com/kr/vehicles/ev9/specification). "
             "셀 구성 정보는 공식 자료 미공개로 NULL."
}
```

**중요**: 공식 출처가 없는 값은 **NULL로 남김**. 추정값 금지.

### 추가 정보 필요

- [ ] 배터리 셀 수 (288? 공식 확인 필요)
- [ ] 모듈 수
- [ ] 정격 전압
- [ ] LDC 출력 전압
- [ ] 입구 온도 센서 위치

## 구현 우선순위

### Phase 1 (필수)

- [ ] DB 마이그레이션: `manual_model_id` 추가
- [ ] 기아 EV9 차종 정의 추가 (공식 스펙만)
- [ ] 재해석 로직 구현
- [ ] API 엔드포인트 추가
- [ ] 테스트 작성

### Phase 2 (선택)

- [ ] UI: 차종 선택 모달
- [ ] 차종 지정 이력 추적
- [ ] 다른 인기 모델 추가 (아이오닉5, EV6, 코나 등)

## 테스트

### 시나리오 테스트

```python
def test_manual_model_selection():
    """관리자가 차종을 지정하면 재해석된다."""
    
    # 1. VIN으로 모델 미확인 스캔 생성
    inspection = create_inspection(vin="KM...", maker="기아", model=None)
    assert inspection.overall_judgment == "판정보류"
    
    # 2. EV9 차종 정의 적용
    ev9_def = VehicleDefinition.query.filter_by(model="EV9").first()
    reinterpret_with_model(inspection.id, ev9_def.id)
    
    # 3. 재해석 결과 확인
    db.session.refresh(inspection)
    assert inspection.manual_model_id == ev9_def.id
    assert inspection.overall_judgment == "양호"  # 재판정
```

## 참고

- `app/modules/definitions/models.py`: VehicleDefinition
- `app/modules/admin/battery/`: 배터리 스펙 관리
- `app/modules/scanner/service.py`: 스캔 해석 로직
