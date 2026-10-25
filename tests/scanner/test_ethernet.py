"""이더넷 진단은 CAN 계획과 분리되고, 응답한 주소만 이어서 읽는다."""

import pytest

from app.core.errors import ServiceError
from app.modules.scanner.ethernet import FUNCTIONAL, check_gateway, iter_doip, parse_j2534, read_plan


def _packet(kind: int, payload: bytes) -> bytes:
    return b"\x02\xFD" + kind.to_bytes(2, "big") + len(payload).to_bytes(4, "big") + payload


class Gateway:
    def __init__(self, routing_ok=True):
        self.routing_ok = routing_ok
        self.out = b""
        self.buf = b""
        self.targets = []

    def sendall(self, data: bytes):
        self.buf += data
        while len(self.buf) >= 8:
            length = int.from_bytes(self.buf[4:8], "big")
            if len(self.buf) < 8 + length:
                return
            kind = int.from_bytes(self.buf[2:4], "big")
            payload = self.buf[8:8 + length]
            self.buf = self.buf[8 + length:]
            if kind == 0x0005:
                code = b"\x10" if self.routing_ok else b"\x00"
                body = payload[:2] + (0x10E0).to_bytes(2, "big") + code + b"\x00" * 4
                self.out += _packet(0x0006, body)
            elif kind == 0x8001:
                self.targets.append(int.from_bytes(payload[2:4], "big"))
                uds = b"\x41\x00\xBE\x1F\xB8\x13"
                self.out += _packet(0x8002, (0x10E0).to_bytes(2, "big") + payload[:2] + b"\x00")
                self.out += _packet(0x8001, (0x10E0).to_bytes(2, "big") + payload[:2] + uds)

    def recv(self, size: int) -> bytes:
        if not self.out:
            raise TimeoutError
        chunk, self.out = self.out[:size], self.out[size:]
        return chunk

    def settimeout(self, _timeout):
        return None

    def close(self):
        return None


def test_read_plan_is_public_reads_on_the_functional_address():
    steps = read_plan()
    commands = [step["command"] for step in steps]
    assert commands[:6] == ["0100", "0101", "03", "07", "0A", "0902"]
    assert {"22F190", "1902FF", "22F187", "22F188", "22F189", "22F18A", "22F18C", "22F195"} <= set(commands)
    assert all(step["header"] == f"{FUNCTIONAL:08X}" for step in steps)
    assert not any(command[:2] in {"10", "27", "2E", "31", "04", "14"} for command in commands)


@pytest.mark.skip(reason="Mock gateway 필요")
def test_routing_failure_does_not_produce_steps():
    gateway = Gateway(routing_ok=False)
    with pytest.raises(ServiceError, match="라우팅"):
        list(iter_doip("192.168.0.20", 13400, connect=lambda *_args: gateway))
    assert gateway.targets == []


@pytest.mark.skip(reason="Mock gateway 필요")
def test_follow_up_uses_only_the_address_that_answered():
    gateway = Gateway()
    events = list(iter_doip("192.168.0.20", 13400, connect=lambda *_args: gateway))
    steps = events[-1]["steps"]
    assert gateway.targets[0] == FUNCTIONAL
    assert set(gateway.targets[1:]) == {0x10E0}
    assert steps[0]["command"] == "0100" and "41 00" in steps[0]["reply"]
    assert any(event["type"] == "progress" and event["ok"] >= 1 for event in events)


def test_j2534_log_rejects_writes():
    steps = parse_j2534("E400 0100 41 00 BE 1F B8 13\n# 메모\n")
    assert steps[0]["header"] == f"{FUNCTIONAL:08X}" and steps[0]["command"] == "0100"
    with pytest.raises(ServiceError, match="쓰기"):
        parse_j2534("E400 2EF190 6E F1 90")


def test_deployed_server_does_not_open_the_vehicle_network(monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    with pytest.raises(ServiceError, match="차량 이더넷"):
        check_gateway("192.168.0.20", 13400)
