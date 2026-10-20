"""비트 필드와 부동소수 배치는 바이트 단위 수식이 놓치는 값을 읽는다."""

from app.modules.canlab.engine.search import GroundTruth, Layout, find_candidates


def test_nibble_and_twelve_bit_values():
    high = Layout(0x7E4, 0x0101, 0, 1, bit_length=4)
    low = Layout(0x7E4, 0x0101, 0, 1, bit_offset=4, bit_length=4)
    wide = Layout(0x7E4, 0x0101, 0, 2, bit_length=12)

    assert high.value(bytes.fromhex("5C")) == 5
    assert low.value(bytes.fromhex("5C")) == 12
    assert wide.value(bytes.fromhex("0AE0")) == 174
    assert "4비트" in high.formula() and "12비트" in wide.formula()
    assert Layout.from_dict({"request_id": "7E4", "did": "0101", "start": 0, "width": 1}) == Layout(
        0x7E4, 0x0101, 0, 1)


def test_search_finds_twelve_bit_field():
    samples = {(0x7E4, 0x0101): [(0.0, bytes.fromhex("0AE0"))]}
    found = find_candidates(samples, GroundTruth("pack_voltage", 174, 0), references={})

    match = next(item for item in found if item.layout.bit_length == 12)
    assert match.layout.value(bytes.fromhex("0AE0")) == 174


def test_float32_big_and_little_endian():
    big = Layout(0x7E4, 0x0101, 0, 4, encoding="float32")
    little = Layout(0x7E4, 0x0101, 0, 4, endian="little", encoding="float32")

    assert big.value(bytes.fromhex("415A0000")) == 13.625
    assert little.value(bytes.fromhex("00005A41")) == 13.625
    assert "부동소수" in big.formula()

    samples = {(0x7E4, 0x0101): [(0.0, bytes.fromhex("415A0000"))]}
    found = find_candidates(samples, GroundTruth("aux_voltage", 13.625, 3), references={})
    assert any(item.layout.encoding == "float32" and item.decoded == 13.625 for item in found)
