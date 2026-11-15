"""ISO 15765-2(ISO-TP) 메시지 재조립. 흐름제어 프레임은 버리고 단일·연속 프레임을 합친다."""

from dataclasses import dataclass

from app.modules.canlab.engine.frames import Frame


@dataclass(frozen=True)
class Message:
    t_ms: float
    can_id: int
    payload: bytes
    complete: bool = True


@dataclass
class _Pending:
    t_ms: float
    length: int
    data: bytearray
    next_sn: int


def reassemble(frames: list[Frame]) -> list[Message]:
    """CAN ID마다 따로 재조립한다. 순서가 틀린 연속 프레임은 미완성 메시지로 남긴다."""
    pending: dict[int, _Pending] = {}
    messages: list[Message] = []

    def flush(can_id: int, complete: bool) -> None:
        state = pending.pop(can_id)
        messages.append(Message(state.t_ms, can_id, bytes(state.data[: state.length]), complete))

    for frame in frames:
        data = frame.data
        if not data:
            continue
        pci = data[0] >> 4
        if pci == 0:
            if frame.can_id in pending:
                flush(frame.can_id, complete=False)
            length = data[0] & 0x0F
            if 0 < length <= len(data) - 1:
                messages.append(Message(frame.t_ms, frame.can_id, bytes(data[1 : 1 + length])))
        elif pci == 1 and len(data) >= 2:
            if frame.can_id in pending:
                flush(frame.can_id, complete=False)
            length = ((data[0] & 0x0F) << 8) | data[1]
            pending[frame.can_id] = _Pending(frame.t_ms, length, bytearray(data[2:]), 1)
        elif pci == 2:
            state = pending.get(frame.can_id)
            if state is None:
                continue
            if (data[0] & 0x0F) != state.next_sn:
                flush(frame.can_id, complete=False)
                continue
            state.data.extend(data[1:])
            state.next_sn = (state.next_sn + 1) % 16
            if len(state.data) >= state.length:
                flush(frame.can_id, complete=True)

    for can_id in list(pending):
        flush(can_id, complete=False)
    messages.sort(key=lambda m: m.t_ms)
    return messages


def format_uds_elm_reply(ident: int, payload: bytes) -> str:
    """UDS 응답을 ELM327 ATH1 형식(ISO-TP PCI 포함)으로 변환.
    
    Args:
        ident: CAN ID (≤0x7FF → 3자리, >0x7FF → 8자리)
        payload: UDS 응답 페이로드 (서비스 + 데이터)
    
    Returns:
        ELM ATH1 형식 문자열 (여러 프레임은 '\n'으로 구분)
        
    Raises:
        ValueError: 빈 payload 또는 n>0xFFF
    """
    if not payload:
        raise ValueError("Empty payload")
    
    n = len(payload)
    if n > 0xFFF:
        raise ValueError(f"Payload too long: {n} > 4095")
    
    # CAN ID 형식 (3자리 또는 8자리)
    if ident <= 0x7FF:
        id_str = f"{ident:03X}"
    else:
        id_str = f"{ident:08X}"
    
    frames = []
    
    if n <= 7:
        # Single Frame: [0x0n] + payload (8바이트 패딩)
        frame_data = bytes([n]) + payload + bytes(7 - n)
        frame_hex = " ".join(f"{b:02X}" for b in frame_data)
        frames.append(f"{id_str} {frame_hex}")
    else:
        # First Frame: [0x10|(n>>8)&0x0F, n&0xFF] + payload[:6] (8바이트)
        ff_pci = bytes([0x10 | ((n >> 8) & 0x0F), n & 0xFF])
        ff_data = ff_pci + payload[:6]
        ff_hex = " ".join(f"{b:02X}" for b in ff_data)
        frames.append(f"{id_str} {ff_hex}")
        
        # Consecutive Frames: [0x20|sn] + 7바이트 (8바이트 패딩)
        idx = 6
        sn = 1
        while idx < n:
            chunk = payload[idx:idx+7]
            cf_pci = bytes([0x20 | sn])
            cf_data = cf_pci + chunk + bytes(7 - len(chunk))
            cf_hex = " ".join(f"{b:02X}" for b in cf_data)
            frames.append(f"{id_str} {cf_hex}")
            idx += 7
            sn = (sn + 1) % 16
    
    return "\n".join(frames)
