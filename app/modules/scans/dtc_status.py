"""DTC status byte classification (v2.2.20).

UDS 0x19 status byte classification according to ISO 14229:
- 현재 (Current): Active fault, currently present
- 임시 (Temporary): Intermittent fault, occurred this cycle but may clear
- 과거 (Historical): Past fault, no longer active

Status byte bits:
- bit 0: testFailed - test failed at time of request
- bit 1: testFailedThisOperationCycle - failed this driving cycle  
- bit 2: pendingDTC - not yet confirmed
- bit 3: confirmedDTC - confirmed, stored permanently
- bit 4: testNotCompletedSinceLastClear
- bit 5: testFailedSinceLastClear - failed since last clear (historical)
- bit 6: testNotCompletedThisOperationCycle
- bit 7: warningIndicatorRequested - lamp/warning triggered
"""


def classify_dtc_status(status_byte: int | None) -> str | None:
    """Classify DTC status from UDS 0x19 status byte.
    
    Args:
        status_byte: UDS status byte (0x00-0xFF)
    
    Returns:
        '현재' (current), '임시' (temporary), '과거' (historical), or None
    
    Classification logic:
    - 현재: bit 0 (testFailed) OR bit 3 (confirmedDTC) set
    - 임시: bit 1 (testFailedThisOperationCycle) set, but not 현재
    - 과거: bit 5 (testFailedSinceLastClear) set, but not 현재 or 임시
    - None: status byte not available
    """
    if status_byte is None:
        return None
    
    # Bit masks
    TEST_FAILED = 0x01                      # bit 0
    TEST_FAILED_THIS_CYCLE = 0x02           # bit 1
    CONFIRMED_DTC = 0x08                    # bit 3
    TEST_FAILED_SINCE_CLEAR = 0x20          # bit 5
    
    # Current: active fault right now
    if status_byte & (TEST_FAILED | CONFIRMED_DTC):
        return '현재'
    
    # Temporary: failed this cycle but not currently active
    if status_byte & TEST_FAILED_THIS_CYCLE:
        return '임시'
    
    # Historical: failed since clear but not active this cycle
    if status_byte & TEST_FAILED_SINCE_CLEAR:
        return '과거'
    
    # No relevant status bits set (or only bits 2,4,6,7)
    return None
