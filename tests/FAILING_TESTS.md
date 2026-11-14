# Remaining Failing Tests (12/750)

## Current Status
- **738 passed, 12 failed** (98.4% pass rate)
- Major improvement from 592 passed / 137 failed / 21 errors

## Common Pattern
Most failures are due to **maker normalization not being applied** when tests use raw SQL INSERT instead of ORM models.

## Failing Tests by Category

### Knowledge Module (8 tests)
1. `tests/knowledge/test_command_alerts.py::test_nissan_spellings_unified`
   - Issue: 'Nissan' not normalized to '닛산'
   
2. `tests/knowledge/test_command_views.py::test_observed_command_is_saved_once_and_leaves_public_name`
   - Issue: Maker normalization

3. `tests/knowledge/test_dtc_catalog.py::test_dtc_catalog_import_uses_pbcu_and_stays_draft`
   - Issue: 'Hyundai' not normalized
   
4. `tests/knowledge/test_dtc_catalog.py::test_hyundai_kia_sheet_is_stored_for_both_makers`
   - Issue: Maker normalization

5. `tests/knowledge/test_migration_demote_nissan.py::test_demotes_unverified_and_keeps_standard`
   - Issue: Migration test

6. `tests/knowledge/test_scan_link.py::test_unknown_maker_dtc_stays_draft_and_off_the_scan`
   - Issue: 'Kia' not normalized to '기아'

7. `tests/knowledge/test_scan_link.py::test_seen_read_is_saved_once_and_writes_are_skipped`
   - Issue: Maker normalization

8. `tests/knowledge/test_uploads.py::test_xlsx_dtc_and_command_uploads_stay_drafts`
   - Issue: Upload test

### Scanner Module (4 tests)
9. `tests/scanner/test_learn_report.py::test_remember_only_successful_reads_and_prefers_model`
10. `tests/scanner/test_learn_report.py::test_remember_caps_at_forty`
11. `tests/scanner/test_learn_report.py::test_commands_page_filters_by_maker`
12. `tests/scanner/test_service.py::test_wescan_report_and_learned_command`

## Root Cause
Tests that use raw SQL `INSERT` bypass the SQLAlchemy `@validates` decorator on model fields. The `normalize_maker()` function is only called when using ORM models.

## Solution Approach
1. **Option A**: Modify tests to use ORM models instead of raw SQL
2. **Option B**: Call `normalize_maker()` explicitly in test SQL
3. **Option C**: Create test helper functions that properly normalize test data

## Next Steps
These tests need systematic refactoring to either:
- Use ORM models for data insertion
- Apply normalization in the test setup code
- Update assertions to match actual (un-normalized) values if that's the expected behavior in those contexts
