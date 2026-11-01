# TRC fixtures (sanitized)

- Source: PCAN-View traces used for scantest C8–C9 / regression (diagnostic-heavy, not full C-CAN).
- VIN ASCII/hex masked; UDS SecurityAccess (0x27/0x67 41/42) payloads zeroed.
- `synthetic_broadcast.trc`: crafted periodic ID 0x100 for period/change unit tests.
- Do not restore original cert or VIN values into the repo.
