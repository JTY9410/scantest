# Phase 2b: Full Plate Lookup Integration

## Goal
Integrate plate lookup as PRIMARY powertrain source, detect conflicts when plate ≠ VIN, show conflict resolution modal.

## Tasks
1. ✅ Database schema (3fa208f56efc)
2. ✅ powertrain_service.py
3. ✅ Admin API endpoints
4. ✅ Conflict modal UI component
5. ⏳ Wire plate lookup into scan flow
6. ⏳ Show conflict modal in scan results
7. ⏳ Integration tests with synthetic data
8. ⏳ Admin page to list/filter conflicts

## Implementation Notes
- car_info.lookup() already exists and is called in scanner/service.py
- Need to wire classify_vehicle_powertrain into actual vehicle/scan creation
- Show conflict modal when powertrain_conflict = true
- Store both plate and VIN results for comparison
