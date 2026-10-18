"""위카 앱(evolsraet/wecar_scan) main·dev 브랜치의 실차 테스트 벡터로 scantest 해석기가 같은 값을 내는지 확인한다.

- 앱이 맞게 읽던 값(VIN, 고장코드, 22 0101 SOC·전압·전류·온도·셀 전압, 동작시간, 절연저항)은 같아야 한다.
- 앱의 알려진 오류는 따라 하지 않는다: 19 15(59 15) 무시, SOH = 100 - (22 0101 b26 ÷ 10).
  b26은 최저 셀 '번호'라서 SOH가 아니다. SOH는 22 0105(OBDb·공개 자료 b25~26 × 0.1)에서 읽는다.
"""

import pytest

from app.modules.canlab.engine import obdb
from app.modules.canlab.engine.search import Layout, load_references
from app.modules.scanner import obd

# wecar_scan main test/vin_parsing_test.dart:30,36
VIN_0902 = "7E8 10 14 49 02 01 4B 4D 48\n7E8 21 4B 33 38 31 45 47 4D\n7E8 22 55 30 35 30 39 35 39"
VIN_F190 = "7EA 10 14 62 F1 90 4B 4E 41\n7EA 21 43 35 38 31 43 50 53\n7EA 22 41 32 32 35 39 31 35"
# main test/standard_dtc_parsing_test.dart:51
DTC_07 = "\n".join(["7E8 10 10 47 07 22 51 00 30", "7E8 21 03 01 03 03 03 04 03", "7E8 22 02 03 00 AA AA AA AA",
                    "7EA 02 47 00 00 00 00 00 00"])
# main test/uds_dtc_parsing_test.dart:30
UDS_190204 = "7ED 03 59 02 FF AA AA AA AA\n7EC 07 59 02 FF D1 19 00 27"
# main test/ev_pid_parsing_test.dart:30 (코나·니로 계열 추정, 7EC)
EV_0101_MAIN = "\n".join([
    "7EC 10 3E 62 01 01 FF F7 E7", "7EC 21 FF 3B 00 00 00 00 80", "7EC 22 00 00 0D D5 17 15 15",
    "7EC 23 15 15 17 00 00 17 B4", "7EC 24 20 B4 01 00 00 77 00", "7EC 25 04 07 07 00 04 09 CC",
    "7EC 26 00 01 7E 35 00 01 73", "7EC 27 C6 00 7C 9A 77 09 00", "7EC 28 03 00 00 00 00 03 E8"])
# dev test/ev_pid_parsing_test.dart:49 (EV6 상용 진단기 로그)
EV6_0101 = "\n".join([
    "7EC 10 3E 62 01 01 EF FB E7", "7E4 30 08 02 00 00 00 00 00", "7EC 21 EF 35 00 00 00 00 00",
    "7EC 22 00 04 1A D2 1A 17 1A", "7EC 23 19 18 18 18 00 41 B2", "7EC 24 02 B2 0B 00 00 90 00",
    "7EC 25 00 71 19 00 00 70 D7", "7EC 26 00 00 53 C2 00 00 50", "7EC 27 6D 00 38 57 57 00 02",
    "7EC 28 AF 00 00 00 00 06 C3"])
# dev test/ev_pid_parsing_test.dart:31
EV6_0105 = "\n".join([
    "7E4 03 22 01 05 00 00 00 00", "7EC 10 2E 62 01 05 FF FB 74", "7E4 30 08 02 00 00 00 00 00",
    "7EC 21 0F 01 2C 01 01 2C 18", "7EC 22 17 18 18 18 18 18 6C", "7EC 23 34 61 62 00 00 50 19",
    "7EC 24 00 03 E8 B5 1F 43 00", "7EC 25 2F 00 00 00 00 00 00", "7EC 26 00 18 18 18 19 AA AA"])


def _payloads(command: str, reply: str) -> list[bytes]:
    outcome = obd.evaluate(command, reply, "can11")
    assert outcome.status == "ok", outcome.message
    return [p for ps in outcome.positive.values() for p in ps]


def _data(command: str, reply: str) -> bytes:
    """22 DID 응답에서 에코(62 + DID 2바이트)를 뗀 데이터. references·OBDb의 start는 이 데이터 기준."""
    return _payloads(command, reply)[0][3:]


def test_vin_matches_app():
    assert obd.vin_from("0902", _payloads("0902", VIN_0902)) == "KMHK381EGMU050959"
    assert obd.vin_from("22F190", _payloads("22F190", VIN_F190)) == "KNAC581CPSA225915"


def test_dtcs_match_app():
    assert sorted(obd.obd_dtcs(_payloads("07", DTC_07), "can11")) == [
        "P0030", "P0300", "P0301", "P0302", "P0303", "P0304", "P2251"]
    assert [d["code"] for p in _payloads("190204", UDS_190204) for d in obd.uds_dtcs(p)] == ["U111900"]


def test_permanent_uds_dtcs_are_read_unlike_app_main():
    # 앱 main 파서는 59 02만 찾아 19 15 응답을 늘 빈 목록으로 돌려줬다.
    codes = [d for p in _payloads("1915", "7EC 07 59 15 FF D1 19 00 08") for d in obd.uds_dtcs(p)]
    assert codes and codes[0]["code"] == "U111900" and codes[0]["confirmed"]


def _reference(data: bytes, did: str) -> dict[str, float]:
    out = {}
    for item in load_references()["hypotheses"]:
        if item["did"] == did and (value := Layout.from_dict(item).value(data)) is not None:
            out[item["signal"]] = value
    return out


def test_bms_0101_reference_matches_app_values():
    ref = _reference(_data("220101", EV_0101_MAIN), "0101")
    assert ref["soc"] == 29.5 and ref["pack_voltage"] == 354.1 and ref["pack_current"] == 0.0
    assert (ref["max_temp"], ref["min_temp"]) == (23, 21)
    assert ref["max_cell_v"] == ref["min_cell_v"] == pytest.approx(3.6)
    # 앱 SOH(99.9) = 100 - b26/10 이지만 b26(=1)은 최저 셀 번호다.
    assert ref["min_cell_no"] == 1 and "soh" not in ref


def test_ev6_obdb_matches_app_and_reads_real_soh():
    model = obdb.match({"diag_model": "EV6"})
    assert model and model["repo"] == "Kia-EV6"
    data = {"0101": _data("220101", EV6_0101), "0105": _data("220105", EV6_0105)}
    values = {key: layout.value(data[f"{layout.did:04X}"]) for key, layout, _ in obdb.signal_layouts(model)
              if f"{layout.did:04X}" in data}
    # 앱 dev 테스트 기대값과 같다
    assert values["soc"] == 26.5 and values["pack_voltage"] == 686.6 and values["pack_current"] == 0.4
    assert (values["max_temp"], values["min_temp"]) == (26, 23)
    assert values["operating_time_s"] == 3692375 and values["isolation_kohm"] == 1731
    # 앱은 SOH 98.9(=100 - 최저셀번호 11/10)를 냈지만 OBDb는 22 0105에서 100.0을 읽는다.
    assert values["soh"] == 100.0
