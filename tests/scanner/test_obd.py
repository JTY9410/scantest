from app.modules.canlab.engine.decode import load_trace
from app.modules.canlab.engine.frames import elm_from_exchanges, reply_frames
from app.modules.scanner import obd


def test_protocol_from_atdpn():
    assert obd.protocol_of("A6\r\r>") == ("6", "ISO 15765-4 CAN (11비트, 500 kbaud)", "can11")
    assert obd.protocol_of("3")[2] == "serial"
    assert obd.protocol_of("?")[0] is None


def test_mode01_formulas_follow_j1979():
    reply = "7E8 04 41 0C 1A F8\r7E8 03 41 05 7B\r\r"
    outcome = obd.evaluate("010C", reply, "can11")
    assert outcome.status == "ok"
    assert obd.mode01(outcome.positive[0x7E8][0]) == {"key": "rpm", "label": "엔진 회전수", "unit": "rpm",
                                                      "value": 1726.0}
    assert obd.mode01(bytes.fromhex("41057B"))["value"] == 83
    assert obd.mode01(bytes.fromhex("41422FA8"))["value"] == 12.2
    assert obd.mode01(bytes.fromhex("41A6000186A0"))["value"] == 10000.0
    assert obd.monitor_status(bytes.fromhex("41018307E100")) == {"mil": True, "dtc_count": 3}


def test_supported_pid_bitmap():
    assert {0x01, 0x05, 0x0C, 0x0D, 0x20} <= obd.supported_pids([bytes.fromhex("4100" "88180001")])
    assert 0x02 not in obd.supported_pids([bytes.fromhex("4100" "88180001")])


def test_mode03_dtcs_on_can_and_kline():
    can = obd.evaluate("03", "7E8 06 43 02 01 33 C1 23\r\r", "can11")
    assert obd.obd_dtcs(can.positive[0x7E8], "can11") == ["P0133", "U0123"]

    kline = obd.evaluate("03", "48 6B 10 43 01 33 00 00 00 00 AB\r\r", "serial")
    assert kline.status == "ok" and list(kline.positive) == [0x10]
    assert obd.obd_dtcs(kline.positive[0x10], "serial") == ["P0133"]


def test_vin_multi_frame_can_and_kline():
    can_reply = ("7E8 10 14 49 02 01 4B 4E 41\r7E8 21 44 48 38 31 32 33 34\r"
                 "7E8 22 35 36 37 38 39 30 31\r\r")
    outcome = obd.evaluate("0902", can_reply, "can11")
    assert obd.vin_from("0902", outcome.positive[0x7E8]) == "KNADH812345678901"

    cut = obd.evaluate("0902", "7E8 10 14 49 02 01 4B 4E 41\r7E8 21 44 48 38 31 32 33 34\r", "can11")
    assert cut.status == "parse_error"

    lines = ["48 6B 10 49 02 01 00 00 00 4B 00", "48 6B 10 49 02 02 4E 41 44 48 00",
             "48 6B 10 49 02 03 38 31 32 33 00", "48 6B 10 49 02 04 34 35 36 37 00",
             "48 6B 10 49 02 05 38 39 30 31 00"]
    kline = obd.evaluate("0902", "\r".join(lines), "serial")
    assert obd.vin_from("0902", kline.positive[0x10]) == "KNADH812345678901"


def test_errors_are_classified():
    assert obd.evaluate("0105", "NO DATA\r\r>", "can11").status == "no_data"
    unable = obd.evaluate("0100", "SEARCHING...\rUNABLE TO CONNECT\r\r", None)
    assert unable.status == "device_error" and "UNABLE TO CONNECT" in unable.message
    assert "BUS INIT" in obd.evaluate("0100", "BUS INIT: ...ERROR", None).message
    assert obd.evaluate("0100", "?", None).status == "device_error"
    assert "ERR94" in obd.evaluate("0100", "ERR94", None).message
    assert obd.evaluate("0100", None, None).status == "timeout"
    assert obd.evaluate("0100", "", None, client_error="disconnected").status == "disconnected"

    negative = obd.evaluate("22F190", "7EC 03 7F 22 31\r\r", "can11")
    assert negative.status == "negative" and "NRC 31" in negative.message and "지원하지 않는 DID" in negative.message

    pending = obd.evaluate("220101", "7EC 03 7F 22 78\r7EC 03 7F 22 22\r", "can11")
    assert pending.negative == {0x7EC: 0x22}


def test_uds_dtcs_and_systems():
    payload = bytes.fromhex("5902FF" "0A7F00" "09" "C12300" "08")
    dtcs = obd.uds_dtcs(payload)
    assert [d["code"] for d in dtcs] == ["P0A7F00", "U012300"]
    assert dtcs[0]["active"] and dtcs[0]["confirmed"]
    assert [obd.dtc_system(c) for c in ("P0301", "P0741", "C1234", "U0100", "B1000")] == [
        "engine", "transmission", "chassis", "network", "body"]


def test_kline_frames_are_kept_in_record_but_not_reassembled():
    assert reply_frames("48 6B 10 41 0C 1A F8 C5", "serial")[0].data == bytes.fromhex("410C1AF8")
    assert reply_frames("18 DA F1 10 03 41 0D 20", "can29")[0].source == 0x18DAF110

    text = elm_from_exchanges(
        [{"t_ms": 1, "header": "7DF", "command": "010D", "reply": "48 6B 10 41 0D 20 C5"}],
        {"protocol": "ISO 9141-2"}, bus="serial")
    assert "RX K10 41 0D 20" in text
    trace = load_trace(text)
    assert trace.frame_count == 2 and trace.skipped_lines == 0 and trace.transactions == []
