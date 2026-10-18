"""Knowledge base models for diagnostic commands, decode formulas, DTC meanings, and terms."""
from datetime import datetime
from typing import Literal

from sqlalchemy import Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db

VerificationStatus = Literal["draft", "verified", "deprecated"]
SourceType = Literal["reverse_analysis", "obdb", "public_docs", "web_search", "ai_research", "manual", "wescan"]


class KnowledgeCommand(db.Model):
    """Vehicle diagnostic command (UDS/OBD-II)."""
    __tablename__ = "knowledge_commands"

    id: Mapped[int] = mapped_column(primary_key=True)
    
    # Scoping
    maker: Mapped[str | None] = mapped_column(String(50), index=True)
    model: Mapped[str | None] = mapped_column(String(100))
    year_from: Mapped[int | None]
    year_to: Mapped[int | None]
    ecu_name: Mapped[str | None] = mapped_column(String(100), index=True)
    
    # Command details
    header: Mapped[str | None] = mapped_column(String(10))
    command: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    label: Mapped[str | None] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    
    # Metadata
    source: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    source_detail: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(default=1.0)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft", index=True)
    
    verified_by: Mapped[int | None]
    verified_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_knowledge_commands_scope", "maker", "model", "ecu_name"),
    )


class KnowledgeFormula(db.Model):
    """Decode formula for interpreting diagnostic responses."""
    __tablename__ = "knowledge_formulas"

    id: Mapped[int] = mapped_column(primary_key=True)
    
    # Scoping
    maker: Mapped[str | None] = mapped_column(String(50), index=True)
    model: Mapped[str | None] = mapped_column(String(100))
    year_from: Mapped[int | None]
    year_to: Mapped[int | None]
    ecu_name: Mapped[str | None] = mapped_column(String(100), index=True)
    
    # Formula details
    command: Mapped[str | None] = mapped_column(String(200), index=True)
    pid: Mapped[str | None] = mapped_column(String(20), index=True)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    formula: Mapped[str] = mapped_column(Text, nullable=False)
    unit: Mapped[str | None] = mapped_column(String(20))
    example_input: Mapped[str | None] = mapped_column(String(500))
    example_output: Mapped[str | None] = mapped_column(String(200))
    notes: Mapped[str | None] = mapped_column(Text)
    
    # Metadata
    source: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    source_detail: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(default=1.0)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft", index=True)
    
    verified_by: Mapped[int | None]
    verified_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_knowledge_formulas_scope", "maker", "model", "ecu_name"),
    )


class KnowledgeDTC(db.Model):
    """DTC (Diagnostic Trouble Code) meaning."""
    __tablename__ = "knowledge_dtcs"

    id: Mapped[int] = mapped_column(primary_key=True)
    
    # Scoping
    maker: Mapped[str | None] = mapped_column(String(50), index=True)
    model: Mapped[str | None] = mapped_column(String(100))
    year_from: Mapped[int | None]
    year_to: Mapped[int | None]
    ecu_name: Mapped[str | None] = mapped_column(String(100), index=True)
    
    # DTC details
    code: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str | None] = mapped_column(String(20))
    category: Mapped[str | None] = mapped_column(String(50))
    notes: Mapped[str | None] = mapped_column(Text)
    
    # Metadata
    source: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    source_detail: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(default=1.0)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft", index=True)
    
    verified_by: Mapped[int | None]
    verified_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_knowledge_dtcs_scope", "maker", "model", "ecu_name"),
        Index("ix_knowledge_dtcs_code", "code", "maker"),
    )


class KnowledgeTerm(db.Model):
    """Glossary term for diagnostic concepts."""
    __tablename__ = "knowledge_terms"

    id: Mapped[int] = mapped_column(primary_key=True)
    
    # Term details
    term: Mapped[str] = mapped_column(String(100), nullable=False, index=True, unique=True)
    abbreviation: Mapped[str | None] = mapped_column(String(20))
    definition: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str | None] = mapped_column(String(50), index=True)
    related_terms: Mapped[str | None] = mapped_column(Text)
    
    # Metadata
    source: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    source_detail: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft", index=True)
    
    verified_by: Mapped[int | None]
    verified_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(default=func.now(), onupdate=func.now(), nullable=False)
