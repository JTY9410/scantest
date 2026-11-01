"""DBC 내보내기: 레이아웃 환산과 SG_ 표기가 일치해야 한다."""

import pytest

from app.core.errors import ServiceError
from app.modules.canlab.engine.search import Layout
from app.modules.canlab import service


def test_dbc_signal_roundtrip_little_rpm():
    layout = Layout(0x7E0, 0xE001, 2, 2, endian="little", scale=0.25, offset=0.0)
    line = service._dbc_signal("pack_voltage", layout)
    assert "16|16@1+" in line.replace(" ", "")
    assert "0.25" in line
    data = b"\x00\x00" + (2908).to_bytes(2, "little")
    assert layout.value(data) == 727.0


def test_dbc_export_requires_flag(monkeypatch):
    monkeypatch.setenv("CANLAB_DBC_EXPORT", "0")
    with pytest.raises(ServiceError):
        service.export_dbc(None)
