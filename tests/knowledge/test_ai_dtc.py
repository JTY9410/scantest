"""Test AI-powered DTC lookup.

AI 클라이언트는 mock하여 실제 API 호출 없이 테스트합니다.
"""

import pytest
from unittest.mock import Mock, patch

from app.modules.knowledge.ai_dtc import AIClient, lookup_and_cache_dtc
from app.modules.knowledge.models import KnowledgeDTC


def test_ai_client_not_available_without_key():
    """API 키가 없으면 사용 불가."""
    with patch.dict("os.environ", {}, clear=True):
        client = AIClient()
        assert not client.is_available()


def test_ai_client_available_with_key():
    """API 키가 있으면 사용 가능."""
    with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"}):
        client = AIClient()
        assert client.is_available()


def test_lookup_dtc_returns_none_without_key(app):
    """API 키가 없으면 None 반환."""
    with app.app_context():
        with patch.dict("os.environ", {}, clear=True):
            result = lookup_and_cache_dtc("P0420")
            assert result is None


def test_lookup_dtc_with_mocked_ai(app):
    """Mock AI 클라이언트로 DTC 조회."""
    from app.extensions import db
    
    with app.app_context():
        with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"}):
            with patch("app.modules.knowledge.ai_dtc.AIClient.lookup_dtc") as mock_lookup:
                # Return complete dict with all fields
                mock_lookup.return_value = {
                    "description": "촉매 효율 저하",
                    "subsystem": "배기",
                    "severity": "주의",
                    "rationale": "표준 OBD-II 규격",
                    "detail_name": None
                }
                
                result = lookup_and_cache_dtc("P0420", maker="현대", model="아이오닉5", year=2023)
                
                # Commit to ensure DB save
                db.session.commit()
                
                assert result is not None
                assert result.code == "P0420"
                assert result.description == "촉매 효율 저하"
                assert result.source == "ai"
                assert result.status == "draft"
                assert result.confidence == 0.6


def test_ai_lookup_isolation(app):
    """AI 조회 실패가 예외를 발생시키지 않음."""
    with app.app_context():
        with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"}):
            with patch("app.modules.knowledge.ai_dtc.AIClient.lookup_dtc") as mock_lookup:
                mock_lookup.side_effect = Exception("API error")
                
                # Should not raise
                result = lookup_and_cache_dtc("P0420")
                assert result is None


def test_ai_dtc_cached(app):
    """검증된 DTC는 AI 조회하지 않음."""
    from app.extensions import db
    
    with app.app_context():
        # Create a verified DTC (not draft)
        dtc = KnowledgeDTC(
            code="P0420",
            maker="현대",
            description="촉매 효율 저하",
            source="manual",
            status="verified",
            confidence=1.0
        )
        db.session.add(dtc)
        db.session.commit()
        
        with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"}):
            with patch("app.modules.knowledge.ai_dtc.AIClient.lookup_dtc") as mock_lookup:
                # Should not call AI for verified DTC
                result = lookup_and_cache_dtc("P0420", maker="현대")
                
                # Should return cached verified result
                assert result is not None
                assert result.code == "P0420"
                assert result.status == "verified"
                # AI should not be called
                mock_lookup.assert_not_called()
