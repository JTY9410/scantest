# Adaptive Collection Integration Points (v2.2.25)

## Call Points

### 1. Profile Application
**File**: `app/modules/scanner/service.py`  
**Line**: 306  
**Function**: `apply_profile_if_enabled()`  
**Context**: Called after `build_plan()` to filter scan steps based on approved collection profile

```python
# Line 300-314 in service.py
steps_to_execute = build_plan(car, expand=False)["steps"]

# Apply collection profile (v2.2.25)
from app.modules.scanner.profile_hook import apply_profile_if_enabled
car_maker = car.get('maker') if car else None
car_model = car.get('model') if car else None
force_full = car.get('force_full_scan', False) if car else False
steps_to_execute, profile_id_used, was_full = apply_profile_if_enabled(
    steps_to_execute, car_maker, car_model, force_full_scan=force_full
)
```

### 2. Usage Stats Recording
**File**: `app/modules/scanner/profile_hook.py`  
**Function**: `record_usage_if_enabled()`  
**Status**: Defined but not yet called (planned for post-scan stats update)

## End-to-End Test
**File**: `tests/scanner/test_adaptive_e2e.py`  
- Verifies profile application in scan flow
- Tests force_full_scan bypass
- Validates integration call points
