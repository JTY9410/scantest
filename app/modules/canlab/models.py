import enum
import os
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


class ScopeMixin:
    """적용 범위. 제조사·모델이 있으면 차종, 제조사만 있으면 제조사, 둘 다 없으면 공통."""

    maker: Mapped[str | None] = mapped_column(String(50))
    model: Mapped[str | None] = mapped_column(String(100))

    @property
    def scope_label(self) -> str:
        if self.maker and self.model:
            return f"차종 {self.maker} {self.model}"
        if self.maker:
            return f"제조사 {self.maker}"
        return "공통"


class CanDataset(ScopeMixin, TimestampMixin, db.Model):
    """업로드하거나 수집한 원본 파일. 내용은 필요할 때만 읽는다. maker·model은 차량번호 조회로 정한 차종."""

    __tablename__ = "can_datasets"
    __table_args__ = (
        CheckConstraint("kind IN ('gscan_trc', 'wecan_trc', 'live_capture', 'gscan_pdf')", name="kind_valid"),
        CheckConstraint("source IN ('upload', 'web', 'app', 'lte')", name="source_valid"),
        Index("ix_can_datasets_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer(), "sqlite"),
        primary_key=True
    )
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

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer(), "sqlite"),
        primary_key=True
    )
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


class AnalysisRun(ScopeMixin, db.Model):
    """역산 실행 기록. 입력, 신호별 판정, 새로 적용한 규칙을 남긴다."""

    __tablename__ = "analysis_runs"
    __table_args__ = (Index("ix_analysis_runs_created_at", "created_at"),)

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer(), "sqlite"),
        primary_key=True
    )
    # 차량번호 조회 결과: {car_no, maker, model, submodel, grade, year, registered}
    vehicle: Mapped[dict | None] = mapped_column(JSON)
    # 1단계 리버스 해석: [{header, did, command, example, values: [{label, value, unit, source}]}]
    interpretation: Mapped[list[dict]] = mapped_column(JSON, default=list, server_default="[]")
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


class DecodeRule(ScopeMixin, TimestampMixin, db.Model):
    """신호 하나를 물리값으로 바꾸는 수식. 신호·범위마다 적용 중(active) 규칙은 하나뿐이다."""

    __tablename__ = "decode_rules"
    __table_args__ = (
        CheckConstraint("status IN ('candidate', 'active', 'retired')", name="status_valid"),
        CheckConstraint("endian IN ('big', 'little')", name="endian_valid"),
        Index("uq_decode_rules_active_scope", "signal_key", text("coalesce(maker, '')"),
              text("coalesce(model, '')"), unique=True, postgresql_where=text("status = 'active'")),
        Index("ix_decode_rules_signal_key", "signal_key", "revision"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer(), "sqlite"),
        primary_key=True
    )
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


class ScanLogic(ScopeMixin, TimestampMixin, db.Model):
    """스캔하기가 보내는 추가 명령과 쓰는 수식 묶음(디코딩 규칙 후보). 범위마다 적용 중(active) 버전은 하나뿐이다.

    commands: [{header, command, label}], rules: [{signal_key, rule_id, revision, formula}]
    diff: 항목별 변경 전·후와 과거 데이터 비교(backtest), ai_advice: {provider, summary, items: {key: {choice, reason}}}
    """

    __tablename__ = "scan_logics"
    
    # Build table_args conditionally: include partial unique index only for non-SQLite
    _base_table_args = [
        CheckConstraint("status IN ('draft', 'active', 'retired')", name="status_valid"),
        Index("ix_scan_logics_revision", "revision"),
    ]
    
    # Only add the partial unique index if not using SQLite (for tests)
    # SQLite in-memory is used when TESTING=True or TEST_DATABASE_URL contains sqlite
    _is_sqlite_test = (
        os.environ.get("TESTING") == "True" or 
        "sqlite" in os.environ.get("TEST_DATABASE_URL", "") or
        "sqlite" in os.environ.get("SQLALCHEMY_DATABASE_URI", "")
    )
    
    if not _is_sqlite_test:
        from sqlalchemy import text
        _base_table_args.append(
            Index("uq_scan_logics_active_scope", 
                  text("coalesce(maker, '')"), 
                  text("coalesce(model, '')"),
                  unique=True, 
                  postgresql_where=text("status = 'active'"))
        )
    
    __table_args__ = tuple(_base_table_args)

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer(), "sqlite"),
        primary_key=True
    )
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


class ChangeAction(enum.StrEnum):
    APPLY = "apply"
    EXPAND = "expand"
    ACTIVATE = "activate"
    RETIRE = "retire"
    ROLLBACK = "rollback"

    @property
    def label(self) -> str:
        return {"apply": "차종 적용", "expand": "제조사 확대", "activate": "규칙 적용", "retire": "규칙 해제",
                "rollback": "되돌리기"}[self.value]


class RuleChange(ScopeMixin, db.Model):
    """범위 하나의 규칙·로직 변경 이력. before·after는 {logic_id, rules: [{signal_key, rule_id, revision, formula}]}.
    되돌리기는 before로 돌아가는 새 이력을 남긴다. 이력은 지우지 않는다."""

    __tablename__ = "rule_changes"
    __table_args__ = (
        CheckConstraint("action IN ('apply', 'expand', 'activate', 'retire', 'rollback')", name="action_valid"),
        Index("ix_rule_changes_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer(), "sqlite"),
        primary_key=True
    )
    action: Mapped[str] = mapped_column(String(10))
    logic_id: Mapped[int | None] = mapped_column(ForeignKey("scan_logics.id", ondelete="SET NULL"))
    before: Mapped[dict] = mapped_column(JSON, default=dict)
    after: Mapped[dict] = mapped_column(JSON, default=dict)
    backtest: Mapped[dict | None] = mapped_column(JSON)
    note: Mapped[str | None] = mapped_column(String(300))
    reverted_by_id: Mapped[int | None] = mapped_column(ForeignKey("rule_changes.id", ondelete="SET NULL"))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    creator: Mapped[User | None] = relationship(lazy="joined")

    @property
    def action_label(self) -> str:
        return ChangeAction(self.action).label


class RuleIncident(ScopeMixin, db.Model):
    """스캔할 때 적용 중 로직·규칙에서 생긴 문제(로직 명령 실패, 수식으로 값을 읽지 못함)."""

    __tablename__ = "rule_incidents"
    __table_args__ = (Index("ix_rule_incidents_created_at", "created_at"),)

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer(), "sqlite"),
        primary_key=True
    )
    scan_id: Mapped[int | None] = mapped_column(BigInteger)
    logic_id: Mapped[int | None] = mapped_column(ForeignKey("scan_logics.id", ondelete="SET NULL"))
    label: Mapped[str] = mapped_column(String(200))
    command: Mapped[str | None] = mapped_column(String(40))
    message: Mapped[str] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    logic: Mapped[ScanLogic | None] = relationship(lazy="joined")


class ReferenceStatus(enum.StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"

    @property
    def label(self) -> str:
        return {"pending": "검토 대기", "approved": "승인", "rejected": "반려"}[self.value]


class CanReference(ScopeMixin, TimestampMixin, db.Model):
    """CAN 해석 참고자료(공개 자료). 승인한 자료의 items만 분석(해석·가점)에 쓴다.

    items: [{signal_key, request_id, did, start, width, endian, signed, scale, offset, note}]
    keywords: 차량정보 모델명·세부모델명에서 찾을 이름(OBDb). 비어 있으면 maker·model로 고른다.
    """

    __tablename__ = "can_references"
    __table_args__ = (
        CheckConstraint("source_type IN ('obdb', 'url')", name="source_type_valid"),
        CheckConstraint("status IN ('pending', 'approved', 'rejected')", name="status_valid"),
        Index("ix_can_references_status", "status"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer(), "sqlite"),
        primary_key=True
    )
    source_type: Mapped[str] = mapped_column(String(10))
    title: Mapped[str] = mapped_column(String(200))
    url: Mapped[str] = mapped_column(String(500), unique=True)
    license: Mapped[str | None] = mapped_column(String(100))
    keywords: Mapped[list[str]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(10), default=ReferenceStatus.PENDING)
    content_text: Mapped[str | None] = mapped_column(Text, deferred=True)
    items: Mapped[list[dict]] = mapped_column(JSON, default=list)
    ai_provider: Mapped[str | None] = mapped_column(String(20))
    problem: Mapped[str | None] = mapped_column(String(300))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")

    __mapper_args__ = {"version_id_col": version}

    @property
    def status_label(self) -> str:
        return ReferenceStatus(self.status).label


class DiagnosticReport(db.Model):
    """운영 결과지. 만든 시점의 규칙 버전과 값을 그대로 보관한다."""

    __tablename__ = "diagnostic_reports"
    __table_args__ = (Index("ix_diagnostic_reports_created_at", "created_at"),)

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer(), "sqlite"),
        primary_key=True
    )
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


class ScanWescanCompare(ScopeMixin, db.Model):
    """스캔 통신기록과 위스캔 결과치 비교. 차이표·AI 요약·규칙 후보(logic)를 남긴다.

    decoded: {signal_key: {label, value, unit, formula?, rule_id?}}
    diff: [{signal_key, label, status, scan_value, wescan_value, unit, note}]
    status: match | mismatch | scan_only | wescan_only | no_rule
    """

    __tablename__ = "scan_wescan_compares"
    __table_args__ = (Index("ix_scan_wescan_compares_created_at", "created_at"),)

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer(), "sqlite"),
        primary_key=True
    )
    scan_dataset_id: Mapped[int] = mapped_column(ForeignKey("can_datasets.id", ondelete="CASCADE"))
    scan_id: Mapped[int | None] = mapped_column(BigInteger)
    analysis_run_id: Mapped[int | None] = mapped_column(ForeignKey("analysis_runs.id", ondelete="SET NULL"))
    logic_id: Mapped[int | None] = mapped_column(ForeignKey("scan_logics.id", ondelete="SET NULL"))
    decoded: Mapped[dict] = mapped_column(JSON, default=dict)
    diff: Mapped[list[dict]] = mapped_column(JSON, default=list)
    ai_summary: Mapped[str | None] = mapped_column(Text)
    ai_provider: Mapped[str | None] = mapped_column(String(20))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    scan_dataset: Mapped[CanDataset] = relationship(lazy="joined", foreign_keys=[scan_dataset_id])
    logic: Mapped[ScanLogic | None] = relationship(lazy="joined")
    creator: Mapped[User | None] = relationship(lazy="joined")
