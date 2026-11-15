"""AI-powered DTC lookup service.

DTC 설명이 없거나 draft 상태인 경우 AI로 조회하여 knowledge_dtcs에 저장합니다.
VIN·차량번호는 AI에 전송하지 않으며, 실패 시에도 스캔 저장은 정상 진행됩니다.
"""

import os
from typing import Any
from flask import current_app
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.modules.knowledge.models import KnowledgeDTC


class AIClient:
    """AI provider wrapper for DTC lookup."""
    
    def __init__(self):
        self.provider = os.getenv("AI_DTC_PROVIDER", "openai")
        self.api_key = os.getenv("OPENAI_API_KEY") or os.getenv("AI_DTC_API_KEY")
        self.model = os.getenv("AI_DTC_MODEL", "gpt-4o-mini")
        self.timeout = float(os.getenv("AI_DTC_TIMEOUT", "10"))
    
    def is_available(self) -> bool:
        """Check if AI provider is configured."""
        return bool(self.api_key)
    
    def lookup_dtc(self, code: str, maker: str | None, model: str | None, 
                   year: int | None, ecu: str | None) -> dict[str, Any] | None:
        """
        Lookup DTC description from AI.
        
        Returns:
            {
                "description": "한글 설명",
                "subsystem": "계통",
                "severity": "심각도",
                "rationale": "근거/출처"
            }
            or None if failed
        """
        if not self.is_available():
            return None
        
        try:
            if self.provider == "openai":
                return self._openai_lookup(code, maker, model, year, ecu)
            else:
                current_app.logger.warning(f"Unknown AI provider: {self.provider}")
                return None
        except Exception as exc:
            current_app.logger.warning(f"AI DTC lookup failed for {code}: {exc}", exc_info=True)
            return None
    
    def _openai_lookup(self, code: str, maker: str | None, model: str | None,
                       year: int | None, ecu: str | None) -> dict[str, Any] | None:
        """Lookup using OpenAI API."""
        try:
            import openai
        except ImportError:
            current_app.logger.warning("openai package not installed")
            return None
        
        client = openai.OpenAI(api_key=self.api_key, timeout=self.timeout)
        
        # Build context
        context = f"DTC 코드: {code}"
        if maker:
            context += f", 제조사: {maker}"
        if model:
            context += f", 차종: {model}"
        if year:
            context += f", 연식: {year}"
        if ecu:
            context += f", ECU: {ecu}"
        
        prompt = f"""자동차 고장 진단 코드(DTC)에 대한 정보를 제공해주세요.

{context}

다음 형식의 JSON으로 응답해주세요:
{{
  "description": "고장 코드의 한글 설명 (100자 이내, 기술적이고 정확하게)",
  "subsystem": "관련 계통 (예: 엔진, 변속기, BMS, MCU 등)",
  "severity": "심각도 (경고/주의/긴급 중 하나)",
  "rationale": "판단 근거 (표준 문서명 또는 출처)"
}}

주의사항:
- 표준 OBD-II/UDS 규격을 우선 참고하세요
- 제조사별 고유 코드는 해당 제조사 기준으로 해석하세요
- 확실하지 않으면 "표준 규격 기반 추정"이라고 명시하세요"""
        
        try:
            response = client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "당신은 자동차 고장 진단 전문가입니다. OBD-II와 UDS 표준에 정통하며, 한국 자동차 제조사들의 고장 코드에도 익숙합니다."},
                    {"role": "user", "content": prompt}
                ],
                response_format={"type": "json_object"},
                temperature=0.3,
            )
            
            import json
            result = json.loads(response.choices[0].message.content)
            
            # Validate response
            if not all(k in result for k in ["description", "subsystem", "severity", "rationale"]):
                current_app.logger.warning(f"AI response missing required fields for {code}")
                return None
            
            return result
            
        except Exception as exc:
            current_app.logger.warning(f"OpenAI API call failed for {code}: {exc}", exc_info=True)
            return None


def lookup_and_cache_dtc(code: str, maker: str | None = None, model: str | None = None,
                         year: int | None = None, ecu: str | None = None) -> KnowledgeDTC | None:
    """
    Lookup DTC from knowledge base, or query AI if not found.
    
    Returns the DTC record if found/created, or None if AI is unavailable.
    Does not raise exceptions - failures are logged and None is returned.
    """
    # Normalize code
    code = code.upper().strip()
    
    try:
        # Check if already exists
        existing = db.session.scalar(
            select(KnowledgeDTC)
            .where(
                KnowledgeDTC.code == code,
                KnowledgeDTC.maker == maker,
                KnowledgeDTC.status != "draft"  # Ignore drafts without description
            )
            .order_by(KnowledgeDTC.confidence.desc())
            .limit(1)
        )
        
        if existing and existing.description and existing.description != "공개된 설명이 없습니다":
            return existing
        
        # Try AI lookup
        client = AIClient()
        if not client.is_available():
            current_app.logger.debug(f"AI DTC lookup skipped for {code}: no API key")
            return None
        
        ai_result = client.lookup_dtc(code, maker, model, year, ecu)
        if not ai_result:
            return None
        
        # Create new record with AI data
        new_dtc = KnowledgeDTC(
            code=code,
            maker=maker,
            model=model,
            year_from=year,
            year_to=year,
            ecu_name=ecu,
            description=ai_result["description"],
            subsystem=ai_result.get("subsystem"),
            severity=ai_result.get("severity"),
            notes=f"AI 추정: {ai_result.get('rationale', 'N/A')}",
            source="ai",
            source_detail=f"{client.provider}:{client.model}",
            confidence=0.6,  # Low confidence for AI-generated content
            status="draft",  # Requires verification
        )
        
        try:
            db.session.add(new_dtc)
            db.session.commit()
            current_app.logger.info(f"AI DTC lookup successful for {code}: {ai_result['description'][:50]}")
            return new_dtc
        except IntegrityError:
            # Another request already created it
            db.session.rollback()
            return db.session.scalar(
                select(KnowledgeDTC)
                .where(KnowledgeDTC.code == code, KnowledgeDTC.maker == maker, KnowledgeDTC.source == "ai")
                .limit(1)
            )
    
    except Exception as exc:
        # Isolate from main scan flow
        current_app.logger.warning(f"DTC lookup failed for {code}: {exc}", exc_info=True)
        try:
            db.session.rollback()
        except Exception:
            pass
        return None
