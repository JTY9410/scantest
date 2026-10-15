import enum
from datetime import datetime

from sqlalchemy import (
    JSON, BigInteger, Boolean, CheckConstraint, DateTime, Float, ForeignKey, Index, Integer,
    LargeBinary, String, Text, text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db
from app.modules.accounts.models import TimestampMixin, User


class DatasetKind(enum.StrEnum):
    GSCAN_TRC = "gscan_trc"
    WECAN_TRC = "wecan_trc"
    LIVE_CAPTURE = "live_capture"
    GSCAN_PDF = "gscan_pdf"

    @property
    def label(self) -> str:
        return {
            "gscan_trc": "리버스 데이터 TRC",
            "wecan_trc": "위스캔 스캔 데이터",
            "live_capture": "블루투스 실시간 수집",
            "gscan_pdf": "G스캔 결과지 PDF(정답값)",
        }[self.value]

    @property
    def is_trace(self) -> bool:
        return self is not DatasetKind.GSCAN_PDF


class DatasetSource(enum.StrEnum):
    UPLOAD = "upload"
    WEB = "web"
    APP = "app"
    LTE = "lte"

    @property
    def label(self) -> str:
        return {"upload": "파일 업로드", "web": "웹 블루투스", "app": "모바일 앱", "lte": "LTE 단말기"}[self.value]


class RuleStatus(enum.StrEnum):
    CANDIDATE = "candidate"
    ACTIVE = "active"
    RETIRED = "retired"

    @property
    def label(self) -> str:
        return {"candidate": "가설(보류)", "active": "적용 중", "retired": "이전 버전"}[self.value]


class TruthSource(enum.StrEnum):
    AI_OCR = "ai_ocr"
    MANUAL = "manual"
    PDF_TEXT = "pdf_text"

    @property
    def label(self) -> str:
        return {"ai_ocr": "AI 판독", "manual": "직접 입력", "pdf_text": "PDF 글자"}[self.value]


class CanDataset(TimestampMixin, db.Model):
    """업로드하거나 수집한 원본 파일. 내용은 필요할 때만 읽는다."""

    __tablename__ = "can_datasets"
    __table_args__ = (
        CheckConstraint("kind IN ('gscan_trc', 'wecan_trc', 'live_capture', 'gscan_pdf')", name="kind_valid"),
        CheckConstraint("source IN ('upload', 'web', 'app', 'lte')", name="source_valid"),
        Index("ix_can_datasets_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    kind: Mapped[str] = mapped_column(String(20))
    source: Mapped[str] = mapped_column(String(10), default=DatasetSource.UPLOAD)
    vehicle: Mapped[str] = mapped_column(String(100))
    filename: Mapped[str] = mapped_column(String(255))
    sha256: Mapped[str] = mapped_column(String(64), unique=True)
    size: Mapped[int] = mapped_column(Integer)
    content: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)
    summary: Mapped[dict] = mapped_column(JSON, default=dict)
    note: Mapped[str | None] = mapped_column(String(500))
    uploaded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    uploader: Mapped[User | None] = relationship(lazy="joined")
    truths: Mapped[list["GroundTruthValue"]] = relationship(
        back_populates="dataset", cascade="all, delete-orphan", order_by="GroundTruthValue.id"
    )

    @property
    def kind_label(self) -> str:
        return DatasetKind(self.kind).label

    @property
    def source_label(self) -> str:
        return DatasetSource(self.source).label

    @property
    def is_trace(self) -> bool:
        return DatasetKind(self.kind).is_trace


class GroundTruthValue(TimestampMixin, db.Model):
    """G-Scan 결과지의 항목 하나. 확인(confirmed)한 숫자 값만 분석에 쓴다."""

    __tablename__ = "ground_truth_values"
    __table_args__ = (
        CheckConstraint("source IN ('ai_ocr', 'manual', 'pdf_text')", name="source_valid"),
        Index("ix_ground_truth_values_dataset_id", "dataset_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("can_datasets.id", ondelete="CASCADE"))
    label: Mapped[str] = mapped_column(String(200))
    signal_key: Mapped[str | None] = mapped_column(String(50))
    value_text: Mapped[str] = mapped_column(String(50))
    unit: Mapped[str | None] = mapped_column(String(20))
    page: Mapped[int | None] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(10), default=TruthSource.MANUAL)
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    dataset: Mapped[CanDataset] = relationship(back_populates="truths")

    @property
    def numeric(self) -> float | None:
        try:
            return float(self.value_text.replace(",", ""))
        except ValueError:
            return None

    @property
    def source_label(self) -> str:
        return TruthSource(self.source).label


class AnalysisRun(db.Model):
    """역산 실행 기록. 입력, 신호별 판정, 새로 적용한 규칙을 남긴다."""

    __tablename__ = "analysis_runs"
    __table_args__ = (Index("ix_analysis_runs_created_at", "created_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    trace_dataset_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    # 위스캔 데이터(truth_dataset_id)와 비교한 리버스 데이터
    reverse_dataset_ids: Mapped[list[int]] = mapped_column(JSON, default=list, server_default="[]")
    truth_dataset_id: Mapped[int | None] = mapped_column(ForeignKey("can_datasets.id", ondelete="SET NULL"))
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    # 명령 비교: {"common": [...], "wescan_only": [...], "reverse_only": [...]}
    commands: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")
    activated_count: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    truth_dataset: Mapped[CanDataset | None] = relationship(lazy="joined")
    creator: Mapped[User | None] = relationship(lazy="joined")


class DecodeRule(TimestampMixin, db.Model):
    """신호 하나를 물리값으로 바꾸는 수식. 신호마다 적용 중(active) 규칙은 하나뿐이다."""

    __tablename__ = "decode_rules"
    __table_args__ = (
        CheckConstraint("status IN ('candidate', 'active', 'retired')", name="status_valid"),
        CheckConstraint("endian IN ('big', 'little')", name="endian_valid"),
        Index("uq_decode_rules_active_signal", "signal_key", unique=True,
              postgresql_where=text("status = 'active'")),
        Index("ix_decode_rules_signal_key", "signal_key", "revision"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    signal_key: Mapped[str] = mapped_column(String(50))
    revision: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(10), default=RuleStatus.CANDIDATE)
    request_id: Mapped[str] = mapped_column(String(8))
    did: Mapped[str] = mapped_column(String(4))
    start: Mapped[int] = mapped_column(Integer)
    width: Mapped[int] = mapped_column(Integer)
    endian: Mapped[str] = mapped_column(String(6), default="big")
    signed: Mapped[bool] = mapped_column(Boolean, default=False)
    scale: Mapped[float] = mapped_column(Float, default=1.0)
    offset: Mapped[float] = mapped_column(Float, default=0.0)
    formula: Mapped[str] = mapped_column(String(200))
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    analysis_run_id: Mapped[int | None] = mapped_column(ForeignKey("analysis_runs.id", ondelete="SET NULL"))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")

    __mapper_args__ = {"version_id_col": version}

    @property
    def status_label(self) -> str:
        return RuleStatus(self.status).label


class LogicStatus(enum.StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    RETIRED = "retired"

    @property
    def label(self) -> str:
        return {"draft": "적용 전(검토 중)", "active": "적용 중", "retired": "이전 버전"}[self.value]


class ScanLogic(TimestampMixin, db.Model):
    """스캔하기가 보내는 추가 명령과 쓰는 수식 묶음. 적용 중(active) 버전은 하나뿐이다.

    commands: [{header, command, label}], rules: [{signal_key, rule_id, revision, formula}]
    diff: 적용 화면의 항목별 변경 전·후, ai_advice: {provider, summary, items: {key: {choice, reason}}}
    """

    __tablename__ = "scan_logics"
    __table_args__ = (
        CheckConstraint("status IN ('draft', 'active', 'retired')", name="status_valid"),
        Index("uq_scan_logics_active", "status", unique=True, postgresql_where=text("status = 'active'")),
        Index("ix_scan_logics_revision", "revision"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    revision: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(10), default=LogicStatus.DRAFT)
    commands: Mapped[list[dict]] = mapped_column(JSON, default=list)
    rules: Mapped[list[dict]] = mapped_column(JSON, default=list)
    diff: Mapped[dict] = mapped_column(JSON, default=dict)
    ai_advice: Mapped[dict | None] = mapped_column(JSON)
    analysis_run_id: Mapped[int | None] = mapped_column(ForeignKey("analysis_runs.id", ondelete="SET NULL"))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")

    creator: Mapped[User | None] = relationship(lazy="joined")

    __mapper_args__ = {"version_id_col": version}

    @property
    def status_label(self) -> str:
        return LogicStatus(self.status).label


class DiagnosticReport(db.Model):
    """운영 결과지. 만든 시점의 규칙 버전과 값을 그대로 보관한다."""

    __tablename__ = "diagnostic_reports"
    __table_args__ = (Index("ix_diagnostic_reports_created_at", "created_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    dataset_id: Mapped[int | None] = mapped_column(ForeignKey("can_datasets.id", ondelete="SET NULL"))
    vehicle: Mapped[str] = mapped_column(String(100))
    values: Mapped[dict] = mapped_column(JSON, default=dict)
    diagnosis: Mapped[dict] = mapped_column(JSON, default=dict)
    rules_used: Mapped[list[dict]] = mapped_column(JSON, default=list)
    ai_summary: Mapped[str | None] = mapped_column(Text)
    ai_provider: Mapped[str | None] = mapped_column(String(20))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    dataset: Mapped[CanDataset | None] = relationship(lazy="joined")
