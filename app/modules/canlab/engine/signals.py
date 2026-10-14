"""분석 대상 신호 목록. G-Scan 결과지 항목명과 신호 키를 잇고 물리적 허용 범위를 정한다."""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Signal:
    key: str
    label: str
    unit: str
    minimum: float
    maximum: float
    aliases: tuple[str, ...] = ()
    # 측정 중에도 값이 움직이는 신호. 정답과 같은 순간의 표본이 하나라도 맞으면 인정한다.
    drifting: bool = False
    # 결과지 정수 표기가 바뀌는 동안 더 벌어질 수 있는 오차(시간 누적값 등)
    extra_tolerance: float = 0.0


SIGNALS: tuple[Signal, ...] = (
    Signal("soc", "배터리 충전 상태(BMS)", "%", 0, 100, ("배터리 충전 상태(BMS)", "SOC")),
    Signal("soc_display", "디스플레이 SOC", "%", 0, 100, ("디스플레이 SOC",)),
    Signal("soh", "배터리 건강 상태(SOH)", "%", 0, 110, ("SOH 상태", "SOH 상태 (신품기준 100%)")),
    Signal("pack_current", "배터리 팩 전류", "A", -1000, 1000, ("배터리 팩 전류",), drifting=True),
    Signal("pack_voltage", "배터리 팩 전압", "V", 0, 1000, ("배터리 팩 전압",), drifting=True),
    Signal("max_temp", "배터리 최대 온도", "°C", -40, 100, ("배터리 최대 온도",)),
    Signal("min_temp", "배터리 최소 온도", "°C", -40, 100, ("배터리 최소 온도",)),
    Signal("module_temp_1", "배터리 모듈 온도 1", "°C", -40, 100,
           ("배터리 모듈 온도 #1", '고전압 배터리 "1번 온도센서"')),
    Signal("module_temp_2", "배터리 모듈 온도 2", "°C", -40, 100,
           ("배터리 모듈 온도 #2", '고전압 배터리 "2번 온도센서"')),
    Signal("module_temp_3", "배터리 모듈 온도 3", "°C", -40, 100,
           ("배터리 모듈 온도 #3", '고전압 배터리 "3번 온도센서"')),
    Signal("module_temp_4", "배터리 모듈 온도 4", "°C", -40, 100,
           ("배터리 모듈 온도 #4", '고전압 배터리 "4번 온도센서"')),
    Signal("module_temp_5", "배터리 모듈 온도 5", "°C", -40, 100, ("배터리 모듈 온도 #5",)),
    Signal("inlet_temp", "배터리 외기(흡기) 온도", "°C", -40, 100, ("배터리 외기 온도",)),
    Signal("max_cell_v", "최대 셀 전압", "V", 1.5, 4.6, ("최대 셀 전압",), drifting=True),
    Signal("max_cell_no", "최대 셀 전압 셀 번호", "", 1, 300, ("최대 셀 전압 셀 번호",), drifting=True),
    Signal("min_cell_v", "최소 셀 전압", "V", 1.5, 4.6, ("최소 셀 전압",), drifting=True),
    Signal("min_cell_no", "최소 셀 전압 셀 번호", "", 1, 300, ("최소 셀 전압 셀 번호",), drifting=True),
    Signal("aux_voltage", "보조(12V) 배터리 전압", "V", 6, 16, ("보조 배터리 전압",), drifting=True),
    Signal("cum_charge_ah", "누적 충전 전류량", "Ah", 0, 10_000_000, ("누적 충전 전류량",), drifting=True),
    Signal("cum_discharge_ah", "누적 방전 전류량", "Ah", 0, 10_000_000, ("누적 방전 전류량",),
           drifting=True),
    Signal("cum_charge_kwh", "누적 충전 전력량", "kWh", 0, 10_000_000, ("누적 충전 전력량",), drifting=True),
    Signal("cum_discharge_kwh", "누적 방전 전력량", "kWh", 0, 10_000_000, ("누적 방전 전력량",),
           drifting=True),
    Signal("operating_time_s", "총 동작 시간", "s", 0, 2_000_000_000, ("총 동작 시간",), drifting=True,
           extra_tolerance=600),
    Signal("inverter_cap_voltage", "인버터 커패시터 전압", "V", 0, 1000, ("인버터 커패시터 전압",),
           drifting=True),
    Signal("isolation_kohm", "절연 저항", "kΩ", 0, 65535, ("절연 저항",)),
    Signal("max_charge_power_kw", "최대 충전 가능 파워", "kW", 0, 1000, ("최대 충전 가능 파워",)),
    Signal("max_discharge_power_kw", "최대 방전 가능 파워", "kW", 0, 1000, ("최대 방전 가능 파워",)),
)

BY_KEY = {signal.key: signal for signal in SIGNALS}


def _normalize(text: str) -> str:
    return re.sub(r"[\s\"'“”]", "", text).lower()


_ALIASES = {_normalize(alias): signal.key for signal in SIGNALS for alias in (signal.label, *signal.aliases)}


def match_label(label: str) -> str | None:
    """G-Scan 항목명을 신호 키로 바꾼다. 모르는 항목은 None."""
    return _ALIASES.get(_normalize(label))


def decimals_of(text: str) -> int:
    text = text.strip()
    return len(text.split(".", 1)[1]) if "." in text else 0


def tolerance(signal_key: str, decimals: int) -> float:
    """결과지는 표시 자릿수에서 반올림되므로 마지막 자리의 절반까지를 같은 값으로 본다."""
    signal = BY_KEY.get(signal_key)
    extra = signal.extra_tolerance if signal else 0.0
    return 0.5 * 10 ** (-decimals) + 1e-9 + extra
