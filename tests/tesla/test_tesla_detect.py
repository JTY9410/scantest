"""Tesla detection tests."""

import pytest
from app.modules.tesla.detect import (
    is_tesla, detect_model, decode_vin, decode_year, extract_vin_from_frames
)


def test_is_tesla_by_vin():
    """VIN WMI로 Tesla 판별."""
    # Tesla VIN
    assert is_tesla([], vin='5YJ3E1EA1LF000001')
    assert is_tesla([], vin='7SAYGDEE1LF000001')
    assert is_tesla([], vin='LRWXGCEK1LC000001')
    
    # Non-Tesla
    assert not is_tesla([], vin='KMHGH4JH3EU000001')  # Hyundai
    assert not is_tesla([], vin='1HGCM82633A000001')  # Honda


def test_is_tesla_by_can_ids():
    """CAN ID 패턴으로 Tesla 판별."""
    # Tesla signature IDs
    frames = [
        (1.0, 0x405, b''),
        (1.1, 0x7FF, b''),
        (1.2, 0x401, b''),
        (1.3, 0x352, b''),
    ]
    assert is_tesla(frames)
    
    # Non-Tesla IDs
    frames = [
        (1.0, 0x7DF, b''),
        (1.1, 0x7E8, b''),
    ]
    assert not is_tesla(frames)


def test_detect_model_from_vin():
    """VIN 4번째 자리로 모델 감지."""
    assert detect_model([], vin='5YJ3E1EA1LF000001') == 'Model 3'
    assert detect_model([], vin='5YJYGDEE1LF000001') == 'Model Y'
    assert detect_model([], vin='5YJSA1E26HF000001') == 'Model S'
    assert detect_model([], vin='5YJXCAE26HF000001') == 'Model X'


def test_decode_vin():
    """VIN 디코딩."""
    vin = '5YJ3E1EA1LF000001'
    result = decode_vin(vin)
    
    assert result['valid']
    assert result['wmi'] == '5YJ'
    assert result['model'] == 'Model 3'
    assert result['year_code'] == 'L'
    assert result['year'] == 2020


def test_decode_year():
    """연식 코드 디코딩."""
    assert decode_year('L') == 2020
    assert decode_year('M') == 2021
    assert decode_year('N') == 2022
    assert decode_year('G') == 2016


def test_extract_vin_from_frames():
    """0x405 멀티플렉스에서 VIN 추출."""
    # VIN "ZZZ12345678901234"를 3개 프레임으로 분할
    frames = [
        (1.0, 0x405, b'\x10ZZZ1234'),  # mux 0x10: 첫 7자
        (1.1, 0x405, b'\x115678901'),  # mux 0x11: 중간 7자
        (1.2, 0x405, b'\x12234\x00\x00\x00'),  # mux 0x12: 마지막 3자
    ]
    
    vin = extract_vin_from_frames(frames)
    assert vin == 'ZZZ12345678901234'


def test_extract_vin_incomplete():
    """불완전한 VIN 프레임."""
    frames = [
        (1.0, 0x405, b'\x10ZZZ1234'),
        # mux 0x11, 0x12 없음
    ]
    
    vin = extract_vin_from_frames(frames)
    assert vin is None
