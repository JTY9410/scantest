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
