"""ISO-TP format_uds_elm_reply 테스트."""

import pytest
from app.modules.canlab.engine.isotp import format_uds_elm_reply, reassemble
from app.modules.canlab.engine.frames import Frame


def test_format_uds_elm_reply_single_frame():
    """Single frame (≤7 bytes): PCI + payload + padding."""
    # 3 bytes: 41 0C 1F
    result = format_uds_elm_reply(0x7E8, bytes([0x41, 0x0C, 0x1F]))
    assert result == "7E8 03 41 0C 1F 00 00 00 00"
    
    # 7 bytes (최대 SF)
    result = format_uds_elm_reply(0x7EC, bytes([0x62, 0x01, 0x01, 0x64, 0x12, 0x34, 0x56]))
    assert result == "7EC 07 62 01 01 64 12 34 56"


def test_format_uds_elm_reply_multi_frame():
    """Multi-frame (>7 bytes): FF + CF frames."""
    # 18 bytes: 49 02 01 + 15 VIN bytes
    vin_payload = bytes([0x49, 0x02, 0x01]) + b"KNDJC811AB70000"
    result = format_uds_elm_reply(0x7E8, vin_payload)
    lines = result.split('\n')
    
    assert len(lines) == 3  # FF + CF1 + CF2
    assert lines[0] == "7E8 10 12 49 02 01 4B 4E 44"  # FF: 18 bytes, first 6
    assert lines[1] == "7E8 21 4A 43 38 31 31 41 42"  # CF1: next 7
    assert lines[2] == "7E8 22 37 30 30 30 30 00 00"  # CF2: last 5 + padding


def test_format_uds_elm_reply_29bit_can_id():
    """29-bit CAN ID (>0x7FF) → 8자리."""
    result = format_uds_elm_reply(0x18DA10F1, bytes([0x50, 0x01]))
    assert result == "18DA10F1 02 50 01 00 00 00 00 00"


def test_format_uds_elm_reply_nrc():
    """Negative Response Code (NRC): 3 bytes."""
    nrc_payload = bytes([0x7F, 0x22, 0x31])  # 7F service code
    result = format_uds_elm_reply(0x7EA, nrc_payload)
    assert result == "7EA 03 7F 22 31 00 00 00 00"


def test_format_uds_elm_reply_empty_payload():
    """빈 payload는 ValueError."""
    with pytest.raises(ValueError, match="Empty payload"):
        format_uds_elm_reply(0x7E8, b"")


def test_format_uds_elm_reply_too_long():
    """n>0xFFF (4095 bytes)는 ValueError."""
    payload = bytes(4096)
    with pytest.raises(ValueError, match="Payload too long"):
        format_uds_elm_reply(0x7E8, payload)


def test_format_uds_elm_reply_reassemble_roundtrip():
    """format → reassemble 왕복 테스트."""
    # 18-byte payload
    original_payload = bytes([0x62, 0xF1, 0x90]) + b"ZZZ1234567890123"  # 3 + 15 = 18
    
    # Format to ELM ATH1
    elm_reply = format_uds_elm_reply(0x7EC, original_payload)
    
    # Parse back to frames
    frames = []
    for i, line in enumerate(elm_reply.split('\n')):
        parts = line.split()
        can_id = int(parts[0], 16)
        data = bytes.fromhex(''.join(parts[1:]))
        frames.append(Frame(t_ms=float(i * 10), can_id=can_id, data=data))
    
    # Reassemble
    messages = reassemble(frames)
    assert len(messages) == 1
    assert messages[0].payload == original_payload
    assert messages[0].complete is True


def test_format_uds_elm_reply_cf_sequence_wraps():
    """CF sequence number wraps at 16."""
    # 112 bytes to get CF sequence wrap (FF:6 + 15*7=105 + 1 = 112)
    payload = bytes([0x62, 0x01, 0x05]) + bytes(109)  # 3 + 109 = 112
    result = format_uds_elm_reply(0x7E4, payload)
    lines = result.split('\n')
    
    # FF (6 bytes) + 16 CFs (106 bytes) = 112 bytes
    # Total: FF + 16 CFs = 17 lines
    assert len(lines) == 17, f"Expected 17 lines, got {len(lines)}"
    # Check CF sequence numbers wrap
    assert lines[15].startswith("7E4 2F")  # CF15 (sn=F, last before wrap)
    assert lines[16].startswith("7E4 20")  # CF16 (sn=0, wrapped)
