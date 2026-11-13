"""BYD Atto 3 방송·BMS 해석.

근거는 2026-11-06 실차 로그 1개(주행거리 7,709km, 차대번호 LGXCE4CB8S2129200)다.
- 확인됨: 그 로그에서 파일명의 값과 같거나, 126개 셀이 3.3V대로 빠짐없이 이어진다.
- 이 배치가 다른 BYD에도 같은지는 이 로그로 확인하지 않는다.
"""

from __future__ import annotations

from app.modules.canlab.engine.uds import mask_vin

BROADCAST_ID = 0x644
CELL_MUX = 0x12
ODO_MUX = 0xE9
BMS_REQUEST = 0x7E7
VIN_DID = 0x1586
CELL_MV_MIN = 2500
CELL_MV_MAX = 4500
CONFIRMED = "확인됨"


def _vin_text(data: bytes) -> str | None:
    text = "".join(chr(b) for b in data if 0x30 <= b <= 0x5A)
    return text[-17:] if len(text) >= 17 else None


def decode(frames, transactions=None) -> dict | None:
    """Atto 3 서명이 있을 때만 주행거리·셀 전압·BMS 차대번호를 돌려준다."""
    cells: dict[int, int] = {}
    odometer = None
    for frame in frames or []:
        data = frame.data
        if frame.can_id != BROADCAST_ID or len(data) < 8:
            continue
        if data[0] == CELL_MUX:
            start = data[1]
            if start < 1 or (start - 1) % 3:
                continue
            for offset in range(3):
                mv = int.from_bytes(data[2 + 2 * offset:4 + 2 * offset], "little")
                if CELL_MV_MIN <= mv <= CELL_MV_MAX:
                    cells[start + offset] = mv
        elif data[0] == ODO_MUX:
            odometer = int.from_bytes(data[6:8], "little")

    vin = None
    for tx in transactions or []:
        if not tx.positive or tx.service != 0x22 or tx.did != VIN_DID:
            continue
        vin = _vin_text(tx.data)
        if vin:
            break

    if not ((cells and odometer is not None) or vin):
        return None

    values = [cells[no] for no in sorted(cells)]
    summary = None
    if values:
        summary = {
            "count": len(values),
            "min_mv": min(values),
            "max_mv": max(values),
            "spread_mv": max(values) - min(values),
            "sum_v": round(sum(values) / 1000, 2),
            "values": [{"no": no, "mv": cells[no]} for no in sorted(cells)],
        }
    return {
        "model": "Atto 3",
        "grade": CONFIRMED,
        "note": "2026-11-06 Atto 3 로그 1대. 셀은 644 mux 12(시작번호 1·4·7…, 리틀엔디언 mV), "
                "주행거리는 644 mux E9 [6:8] 리틀엔디언 km, 차대번호는 7E7 22 1586.",
        "vin": mask_vin(vin),
        "odometer_km": odometer if cells else None,
        "cells": summary,
    }
