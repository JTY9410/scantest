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

    unsupported = obd.evaluate("22F190", "7EC 03 7F 22 31\r\r", "can11")
    assert unsupported.status == "unsupported" and "NRC 31" in unsupported.message \
        and "지원하지 않는 DID" in unsupported.message
    assert obd.evaluate("1902FF", "7E8 03 7F 19 7F\r\r", "can11").status == "unsupported"

    negative = obd.evaluate("220101", "7EC 03 7F 22 78\r7EC 03 7F 22 22\r", "can11")
    assert negative.negative == {0x7EC: 0x22} and negative.status == "negative"

    pending = obd.evaluate("220101", "7EC 03 7F 22 78\r7EC 03 7F 22 78\r", "can11")
    assert pending.status == "pending" and not pending.negative


def test_batched_mode01_and_unspaced_frames():
    outcome = obd.evaluate("010C0D05", "7E8 08 41 0C 1A F8 0D 32 05 7B\r\r", "can11")
    assert outcome.status == "ok"
    values = obd.mode01_values(outcome.positive[0x7E8][0])
    assert [(v["key"], v["value"]) for v in values] == [("rpm", 1726.0), ("speed", 50), ("coolant_temp", 83)]
    assert obd.evaluate("010D0C", "7E8 04 41 0C 1A F8\r\r", "can11").positive

    assert reply_frames("7E8064100983B8013", "can11")[0].data == bytes.fromhex("064100983B8013")
    assert reply_frames("18DAF110034100", "can29")[0].source == 0x18DAF110


def test_readiness_mode06_iumpr_and_snapshot():
    spark = obd.readiness(bytes.fromhex("4101" "81" "07" "65" "21"))
    assert spark["mil"] and spark["dtc_count"] == 1 and spark["ignition"] == "불꽃 점화(가솔린)"
    names = {t["name"]: t["complete"] for t in spark["tests"]}
    assert names == {"실화": True, "연료 계통": True, "종합 부품": True, "촉매": False, "증발가스": True,
                     "산소센서": False, "산소센서 히터": True}
    diesel = obd.readiness(bytes.fromhex("4101" "00" "0F" "C0" "40"))
    assert diesel["ignition"] == "압축 착화(디젤)"
    assert {t["name"]: t["complete"] for t in diesel["tests"]}["PM 필터"] is False

    tests = obd.mode06_tests(bytes.fromhex("46" "21" "80" "0B" "0190" "0064" "03E8" "21" "81" "16" "0640" "0000" "0500"))
    assert tests[0] == {"mid": "21", "name": "촉매 뱅크1", "tid": "80", "value": 0.4, "min": 0.1, "max": 1.0,
                        "unit": "V", "passed": True}
    assert tests[1]["unit"] == "°C" and tests[1]["value"] == 120.0 and tests[1]["passed"] is False

    rate = obd.iumpr("08", [bytes.fromhex("4908" "14" "0010" "0020" "0005" "000A" "0000" "0000")])
    assert rate["conditions"] == 16 and rate["ignitions"] == 32
    assert rate["monitors"][0] == {"name": "촉매 뱅크1", "completed": 5, "conditions": 10, "ratio": 0.5}
    assert rate["monitors"][1]["ratio"] is None

    snapshot = obd.uds_snapshot(bytes.fromhex("5904" "0A7F00" "09" "01" "01" "DD01" "0012"))
    assert snapshot == {"code": "P0A7F00", "status": 9, "record": 1, "did": "DD01", "raw": "00 12"}


def test_uds_dtcs_and_systems():
    payload = bytes.fromhex("5902FF" "0A7F00" "09" "C12300" "08")
    dtcs = obd.uds_dtcs(payload)
    assert [d["code"] for d in dtcs] == ["P0A7F00", "U012300"]
    assert dtcs[0]["active"] and dtcs[0]["confirmed"]
    assert [obd.dtc_system(c) for c in ("P0301", "P0741", "C1234", "U0100", "B1000")] == [
        "engine", "transmission", "chassis", "network", "body"]


def test_extended_pids_freeze_frame_and_ident():
    assert obd.mode01(bytes.fromhex("41030200"))["value"] == "폐회로(산소센서 사용)"
    assert obd.mode01(bytes.fromhex("41142080"))["value"] == 0.16
    assert obd.mode01(bytes.fromhex("4106A0"))["value"] == 25.0
    assert obd.mode01(bytes.fromhex("415E0640"))["value"] == 80.0
    assert obd.mode01(bytes.fromhex("411C01"))["value"] == "OBD-II(CARB)"
    assert obd.freeze_value(bytes.fromhex("420C000FA0"))["value"] == 1000.0
    assert obd.freeze_dtc(bytes.fromhex("4202000143")) == "P0143"
    assert obd.freeze_dtc(bytes.fromhex("4202000000")) is None
    assert obd.cvns([bytes.fromhex("490601" "1A2B3C4D")]) == ["1A2B3C4D"]
    assert obd.ecu_ident(bytes.fromhex("62F187" + "91000-AB12".encode().hex())) == "91000-AB12"
    permanent = obd.uds_dtcs(bytes.fromhex("5915FF" "01010008"))
    assert [d["code"] for d in permanent] == ["P010100"]


def test_kline_frames_are_kept_in_record_but_not_reassembled():
    assert reply_frames("48 6B 10 41 0C 1A F8 C5", "serial")[0].data == bytes.fromhex("410C1AF8")
    assert reply_frames("18 DA F1 10 03 41 0D 20", "can29")[0].source == 0x18DAF110

    text = elm_from_exchanges(
        [{"t_ms": 1, "header": "7DF", "command": "010D", "reply": "48 6B 10 41 0D 20 C5"}],
        {"protocol": "ISO 9141-2"}, bus="serial")
    assert "RX K10 41 0D 20" in text
    trace = load_trace(text)
    assert trace.frame_count == 2 and trace.skipped_lines == 0 and trace.transactions == []
