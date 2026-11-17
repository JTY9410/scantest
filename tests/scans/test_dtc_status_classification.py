"""Test DTC status byte classification (v2.2.20).

UDS 0x19 status byte classification per ISO 14229:
- 현재: bit 0 (testFailed) OR bit 3 (confirmedDTC)
- 임시: bit 1 (testFailedThisOperationCycle) without bits 0/3
- 과거: bit 5 (testFailedSinceLastClear) without bits 0/1/3
"""
import pytest
from app.modules.scans.dtc_status import classify_dtc_status


class TestDtcStatusClassification:
    """Test DTC status byte classification."""

    def test_current_test_failed(self):
        """Bit 0 (testFailed) → 현재."""
        assert classify_dtc_status(0x01) == "현재"
        assert classify_dtc_status(0x0F) == "현재"  # With other bits

    def test_current_confirmed(self):
        """Bit 3 (confirmedDTC) → 현재."""
        assert classify_dtc_status(0x08) == "현재"
        assert classify_dtc_status(0x0C) == "현재"  # With other bits

    def test_temporary_this_cycle(self):
        """Bit 1 (testFailedThisOperationCycle) without 0/3 → 임시."""
        assert classify_dtc_status(0x02) == "임시"
        assert classify_dtc_status(0x06) == "임시"  # With bit 2 (pendingDTC)
        assert classify_dtc_status(0x22) == "임시"  # With bit 5

    def test_temporary_not_current(self):
        """Bit 1 with bits 0 or 3 → 현재 (current overrides temporary)."""
        assert classify_dtc_status(0x03) == "현재"  # bits 0+1
        assert classify_dtc_status(0x0A) == "현재"  # bits 1+3

    def test_historical_since_clear(self):
        """Bit 5 (testFailedSinceLastClear) without 0/1/3 → 과거."""
        assert classify_dtc_status(0x20) == "과거"
        assert classify_dtc_status(0x30) == "과거"  # With bit 4
        assert classify_dtc_status(0xF0) == "과거"  # With bits 4,6,7

    def test_historical_not_current_or_temp(self):
        """Bit 5 with bits 0/1/3 → higher priority status."""
        assert classify_dtc_status(0x21) == "현재"  # bits 0+5
        assert classify_dtc_status(0x22) == "임시"  # bits 1+5
        assert classify_dtc_status(0x28) == "현재"  # bits 3+5

    def test_none_no_relevant_bits(self):
        """No relevant bits set → None."""
        assert classify_dtc_status(0x00) is None
        assert classify_dtc_status(0x10) is None  # Only bit 4
        assert classify_dtc_status(0x40) is None  # Only bit 6
        assert classify_dtc_status(0x80) is None  # Only bit 7
        assert classify_dtc_status(0xD0) is None  # Only bits 4,6,7

    def test_none_missing_status(self):
        """None status byte → None."""
        assert classify_dtc_status(None) is None

    def test_real_world_examples(self):
        """Real-world UDS status byte examples."""
        # Common patterns from actual ECUs
        assert classify_dtc_status(0x0D) == "현재"  # confirmed + testFailed
        assert classify_dtc_status(0x2D) == "현재"  # confirmed + testFailed + since clear
        assert classify_dtc_status(0x24) == "과거"  # testFailedSinceLastClear + testNotCompleted
        assert classify_dtc_status(0x30) == "과거"  # testFailedSinceLastClear + testNotCompleted


class TestDtcStorageIntegration:
    """Integration test: verify DTCs are stored with status classification."""

    def test_classify_function_consistency(self):
        """Verify classify function works correctly for typical scan results."""
        from app.modules.scans.dtc_status import classify_dtc_status
        
        # Verify classification works for bytes that would come from real scans
        assert classify_dtc_status(0x0D) == "현재"   # confirmed + testFailed
        assert classify_dtc_status(0x02) == "임시"   # testFailedThisOperationCycle
        assert classify_dtc_status(0x24) == "과거"   # testFailedSinceLastClear
