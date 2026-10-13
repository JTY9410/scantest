import enum
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, BigInteger, DateTime, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.modules.accounts.models import TimestampMixin


class AiProvider(enum.StrEnum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GEMINI = "gemini"

    @property
    def label(self) -> str:
        return {"openai": "OpenAI", "anthropic": "Anthropic", "gemini": "Google Gemini"}[self.value]


class AiStatus(enum.StrEnum):
    NO_KEY = "no_key"
    UNTESTED = "untested"
    OK = "ok"
    FAILED = "failed"
    REVOKED = "revoked"

    @property
    def label(self) -> str:
        return {
            "no_key": "키 없음",
            "untested": "테스트 전",
            "ok": "연결됨",
            "failed": "연결 실패",
            "revoked": "폐기됨",
        }[self.value]


AI_FEATURES = {
    "explain": "진단 결과 설명",
    "search": "승인 문서 검색",
    "draft": "안내문 초안",
}


class AiConnection(TimestampMixin, db.Model):
    """관리자가 설정하는 외부 AI 연결. 키 평문은 저장하지도, 화면에 다시 내보내지도 않는다."""

    __tablename__ = "ai_connections"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    provider: Mapped[str] = mapped_column(String(20), unique=True)
    model: Mapped[str] = mapped_column(String(100))
    features: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    monthly_budget: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    monthly_token_limit: Mapped[int | None] = mapped_column(Integer)
    key_enc: Mapped[str | None] = mapped_column(Text)
    key_last4: Mapped[str | None] = mapped_column(String(4))
    status: Mapped[str] = mapped_column(String(20), default=AiStatus.NO_KEY)
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_test_message: Mapped[str | None] = mapped_column(String(500))
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")

    __mapper_args__ = {"version_id_col": version}

    @property
    def provider_label(self) -> str:
        return AiProvider(self.provider).label

    @property
    def status_label(self) -> str:
        return AiStatus(self.status).label

    @property
    def has_key(self) -> bool:
        return bool(self.key_enc)
