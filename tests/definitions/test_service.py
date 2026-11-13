"""Tests for definition service functions."""
import pytest

from app.modules.definitions.models import DiagnosticCommand, DbcSignal
from app.modules.definitions.service import decode_signal, update_command_stats


def test_decode_signal_unsigned():
    """Unsigned 신호 디코딩 테스트."""
    signal = DbcSignal(
        message_id=1,
        signal_name="TestSignal",
        start_bit=0,
        bit_length=8,
        byte_order="little",
        value_type="unsigned",
        factor=1.0,
        offset=0.0,
    )
    
    raw_bytes = bytes([42, 0, 0, 0])
    result = decode_signal(signal, raw_bytes)
    assert result == 42.0


def test_decode_signal_with_factor():
    """Factor/offset 적용 테스트."""
    signal = DbcSignal(
        message_id=1,
        signal_name="Voltage",
        start_bit=0,
        bit_length=16,
        byte_order="little",
        value_type="unsigned",
        factor=0.1,
        offset=0.0,
    )
    
    # 400 (0x0190) in little endian = 0x90 0x01
    raw_bytes = bytes([0x90, 0x01, 0, 0])
    result = decode_signal(signal, raw_bytes)
    assert result == pytest.approx(40.0)


def test_update_command_stats_auto_verification(app):
    """자동 검증 승격 테스트."""
    with app.app_context():
        from app.extensions import db
        from app.modules.definitions.models import DefinitionSource
        
        # Create a definition source first
        source = DefinitionSource(
            source_type='obdb',
            file_path='test/obdb.json',
            sha256='a' * 64,
            file_size=1024
        )
        db.session.add(source)
        db.session.flush()
        
        cmd = DiagnosticCommand(
            source_id=source.id,
            source_type='obdb',
            service='22',
            pid='1050',
            command_bytes='22 1050',
            label='Test Command',
            verification_status='needs_verification',
            verification_count=0,
            success_count=0,
            failure_count=0,
        )
        db.session.add(cmd)
        db.session.commit()
        
        # 10회 성공 (80% 이상)
        for _ in range(10):
            update_command_stats(cmd.id, success=True)
        
        db.session.refresh(cmd)
        assert cmd.verification_status == 'verified'
        assert cmd.success_count == 10
        assert cmd.verification_count == 10
