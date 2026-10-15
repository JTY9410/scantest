"""CAN 해석 참고자료 DB: 공개 자료(OBDb 저장소, 관리자가 등록한 URL)를 모아 역산 분석의 해석·가점에 쓴다.

OBDb는 차종 정의를 그대로 변환해 승인 상태로 저장한다. URL 자료는 본문을 받아 AI가 해석 항목 초안을 만들고
관리자가 승인해야 분석에 쓴다(AI는 초안만). URL은 https 공개 주소만 받고 내부·사설 주소는 막는다.
"""

import ipaddress
import math
import re
import socket
from datetime import UTC, datetime
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

import httpx
from sqlalchemy import select
from sqlalchemy.orm import undefer
from sqlalchemy.orm.exc import StaleDataError

from app.core import audit
from app.core.errors import ServiceError
from app.extensions import db
from app.modules.accounts.models import User
from app.modules.canlab import ai
from app.modules.canlab.engine import obdb, signals
from app.modules.canlab.engine.search import Layout, reference_index
from app.modules.canlab.models import CanReference, ReferenceStatus

MAX_BYTES = 1_000_000
MAX_TEXT = 200_000
TIMEOUT_SECONDS = 10
MAX_REDIRECTS = 3
MAX_ITEMS = 200
TEXT_TYPES = ("text/", "application/json", "application/xhtml+xml")
CONFLICT = "다른 관리자가 먼저 바꿨습니다. 새로고침한 뒤 다시 시도하세요."
HEADER = re.compile(r"[0-9A-F]{3}|[0-9A-F]{8}")
REPO = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{2,79}")


def _now() -> datetime:
    return datetime.now(UTC)


# ── 분석에 쓰는 참고 색인 ────────────────────────────────────────────────

def matches(ref: CanReference, car: dict | None) -> bool:
    """자료가 차량에 맞는지. 제조사·모델·키워드가 없는 자료는 모든 차량에 쓴다."""
    if not (ref.maker or ref.model or ref.keywords):
        return True
    if not car:
        return False
    name = obdb._norm(f"{car.get('diag_model') or ''}{car.get('diag_submodel') or ''}")
    if ref.keywords:
        return any(obdb._norm(k) and obdb._norm(k) in name for k in ref.keywords)
    if ref.maker and obdb._norm(ref.maker) != obdb._norm(car.get("diag_company")):
        return False
    return not ref.model or obdb._norm(ref.model) in name


def hypotheses(car: dict | None) -> dict[tuple[str, Layout], list[str]]:
    """(신호, 배치) → 출처. 기본 참고 해석, 이 차종의 OBDb 정의, 승인한 참고자료 중 차량에 맞는 것."""
    index = {key: list(sources) for key, sources in reference_index().items()}

    def add(key: str, layout: Layout, source: str) -> None:
        sources = index.setdefault((key, layout), [])
        if source not in sources:
            sources.append(source)

    if model := obdb.match(car):
        for key, layout, _ in obdb.signal_layouts(model):
            add(key, layout, f"OBDb {model['repo']}")
    for ref in db.session.scalars(select(CanReference).where(CanReference.status == ReferenceStatus.APPROVED)):
        if matches(ref, car):
            for item in ref.items:
                add(item["signal_key"], Layout.from_dict(item), f"참고자료 #{ref.id}")
    return index


def clean_items(raw) -> list[dict]:
    """AI·원본에서 받은 해석 항목을 검사한다. 신호 키, 16진수 주소·DID, 바이트 배치, 유한한 배율만 남긴다."""
    out = []
    for row in raw if isinstance(raw, list) else []:
        if not isinstance(row, dict):
            continue
        try:
            item = {
                "signal_key": str(row.get("signal_key") or ""),
                "request_id": str(row.get("request_id") or "").strip().upper().removeprefix("0X"),
                "did": str(row.get("did") or "").strip().upper().removeprefix("0X").zfill(4),
                "start": int(row.get("start")), "width": int(row.get("width")),
                "endian": "little" if str(row.get("endian") or "big").lower() == "little" else "big",
                "signed": bool(row.get("signed")), "scale": float(row.get("scale", 1)),
                "offset": float(row.get("offset", 0)), "note": str(row.get("note") or "")[:200],
            }
        except (TypeError, ValueError):
            continue
        if (item["signal_key"] not in signals.BY_KEY or not HEADER.fullmatch(item["request_id"])
                or not re.fullmatch(r"[0-9A-F]{4}", item["did"]) or not 0 <= item["start"] <= 255
                or item["width"] not in (1, 2, 4) or not math.isfinite(item["scale"]) or item["scale"] == 0
                or not math.isfinite(item["offset"])):
            continue
        out.append(item)
    return out[:MAX_ITEMS]


# ── 목록·검토 ─────────────────────────────────────────────────────────────

def list_references() -> list[CanReference]:
    return list(db.session.scalars(select(CanReference).order_by(CanReference.status, CanReference.id.desc())))


def get_reference(ref_id: int, with_text: bool = False) -> CanReference:
    options = [undefer(CanReference.content_text)] if with_text else []
    ref = db.session.get(CanReference, ref_id, options=options)
    if ref is None:
        raise ServiceError("참고자료를 찾을 수 없습니다.", 404)
    return ref


def review(actor: User, ref: CanReference, version: int, approve: bool) -> CanReference:
    """관리자가 자료를 승인(분석에 사용)하거나 반려한다."""
    if ref.version != version:
        raise ServiceError(CONFLICT, 409)
    if approve and not ref.items:
        raise ServiceError("해석 항목이 없는 자료는 승인할 수 없습니다. 'AI로 다시 정리'를 먼저 하세요.")
    ref.status = ReferenceStatus.APPROVED if approve else ReferenceStatus.REJECTED
    ref.reviewed_by, ref.reviewed_at = actor.id, _now()
    audit.record("참고자료 승인" if approve else "참고자료 반려", "CanReference", ref.id, user_id=actor.id,
                 changes={"items": len(ref.items), "url": ref.url})
    try:
        db.session.commit()
    except StaleDataError as exc:
        db.session.rollback()
        raise ServiceError(CONFLICT, 409) from exc
    return ref


# ── OBDb 동기화 ──────────────────────────────────────────────────────────

def fetch_obdb(client: httpx.Client, repo: str) -> dict:
    response = client.get(obdb.RAW_URL.format(repo=repo, ref="main"))
    response.raise_for_status()
    return response.json()


def _save_obdb(actor: User, converted: dict) -> CanReference:
    repo = converted["repo"]
    ref = db.session.scalar(select(CanReference).where(CanReference.url == converted["url"]))
    if ref is None:
        ref = CanReference(source_type="obdb", url=converted["url"], created_by=actor.id)
        db.session.add(ref)
    brand, _, name = repo.partition("-")
    ref.title, ref.license, ref.keywords = f"OBDb {repo}", obdb.LICENSE, list(converted["match"])
    ref.maker, ref.model = obdb.MAKERS.get(brand, brand), name.replace("-", " ") or None
    ref.items = clean_items([{"signal_key": s["key"], "request_id": converted["request_id"], "did": s["did"],
                              "start": s["start"], "width": s["width"], "endian": "big", "signed": s["signed"],
                              "scale": s["scale"], "offset": s["offset"], "note": s["id"]}
                             for s in converted["signals"]])
    ref.status, ref.reviewed_by, ref.reviewed_at = ReferenceStatus.APPROVED, actor.id, _now()
    ref.problem = None
    return ref


def sync_obdb(actor: User, extra_repo: str | None = None, extra_keywords: str | None = None) -> tuple[int, list[str]]:
    """OBDb 공개 저장소의 차종 정의를 받아 참고자료로 저장한다. (저장한 수, 실패한 저장소)."""
    repos = dict(obdb.MODELS)
    if extra_repo:
        if not REPO.fullmatch(extra_repo):
            raise ServiceError("OBDb 저장소 이름을 확인하세요(예: Kia-EV6).")
        keywords = [k.strip() for k in (extra_keywords or "").split(",") if k.strip()]
        if not keywords:
            raise ServiceError("추가 저장소의 모델 키워드를 쉼표로 나눠 입력하세요(예: EV6, 이브이식스).")
        repos[extra_repo] = keywords
    saved, failed = 0, []
    with httpx.Client(timeout=TIMEOUT_SECONDS, headers={"User-Agent": "wecarscan-reference/1"}) as client:
        for repo, keywords in repos.items():
            try:
                converted = obdb.convert(repo, "main", fetch_obdb(client, repo), keywords)
            except (httpx.HTTPError, ValueError, KeyError, TypeError):
                converted = None
            if converted is None:
                failed.append(repo)
                continue
            _save_obdb(actor, converted)
            saved += 1
    audit.record("참고자료 OBDb 동기화", "CanReference", user_id=actor.id,
                 changes={"saved": saved, "failed": failed[:20]})
    db.session.commit()
    return saved, failed


# ── URL 자료 ─────────────────────────────────────────────────────────────

def check_url(url: str | None) -> str:
    """https 공개 주소만 받는다. 계정·다른 포트·내부·사설·예약 주소로 이어지는 이름은 막는다."""
    url = (url or "").strip()
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname:
        raise ServiceError("https:// 로 시작하는 공개 주소만 등록할 수 있습니다.")
    if parts.username or parts.password or parts.port not in (None, 443):
        raise ServiceError("주소에 계정이나 다른 포트를 넣을 수 없습니다.")
    try:
        infos = socket.getaddrinfo(parts.hostname, 443, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError) as exc:
        raise ServiceError("주소를 찾을 수 없습니다.") from exc
    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        if not address.is_global or address.is_multicast:
            raise ServiceError("내부·사설 네트워크 주소는 등록할 수 없습니다.")
    return url


class _Text(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg"}
    BLOCK = {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "pre", "table", "section"}

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.title = ""
        self.skip = 0
        self.in_title = False

    def handle_starttag(self, tag, attrs) -> None:
        if tag in self.SKIP:
            self.skip += 1
        elif tag == "title":
            self.in_title = True
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag) -> None:
        if tag in self.SKIP and self.skip:
            self.skip -= 1
        elif tag == "title":
            self.in_title = False
        elif tag in ("td", "th"):
            self.parts.append(" | ")

    def handle_data(self, data) -> None:
        if self.in_title:
            self.title += data
        elif not self.skip:
            self.parts.append(data)


def html_text(source: str) -> tuple[str, str]:
    """HTML을 (본문 글자, 제목)으로. 스크립트·스타일은 뺀다."""
    parser = _Text()
    parser.feed(source)
    text = re.sub(r"[ \t]+", " ", "".join(parser.parts))
    return re.sub(r"\n\s*\n+", "\n", text).strip(), parser.title.strip()


def fetch_text(url: str) -> tuple[str, str]:
    """공개 주소의 글자 자료를 (본문, 제목)으로 받는다. 이동(redirect)할 때마다 주소를 다시 검사한다."""
    current = check_url(url)
    try:
        with httpx.Client(timeout=TIMEOUT_SECONDS, follow_redirects=False,
                          headers={"User-Agent": "wecarscan-reference/1"}) as client:
            for _ in range(MAX_REDIRECTS + 1):
                with client.stream("GET", current) as response:
                    if response.is_redirect:
                        current = check_url(urljoin(current, response.headers.get("location", "")))
                        continue
                    if response.status_code != 200:
                        raise ServiceError(f"자료를 받지 못했습니다(HTTP {response.status_code}).", 502)
                    kind = response.headers.get("content-type", "").lower()
                    if not kind.startswith(TEXT_TYPES):
                        raise ServiceError("글자 자료(HTML·텍스트·JSON)만 등록할 수 있습니다.")
                    body = bytearray()
                    for chunk in response.iter_bytes():
                        body.extend(chunk)
                        if len(body) > MAX_BYTES:
                            raise ServiceError("자료가 너무 큽니다. 1MB 이하만 받을 수 있습니다.", 413)
                    text = body.decode(response.charset_encoding or "utf-8", errors="replace")
                    if "html" in kind:
                        text, title = html_text(text)
                        return text[:MAX_TEXT], title[:200]
                    return text[:MAX_TEXT], ""
    except httpx.TimeoutException as exc:
        raise ServiceError("자료 응답 시간이 초과되었습니다.", 504) from exc
    except httpx.HTTPError as exc:
        raise ServiceError("자료를 받지 못했습니다. 주소를 확인하세요.", 502) from exc
    raise ServiceError("다른 주소로 너무 많이 이동합니다.", 502)


def _extract(ref: CanReference) -> None:
    try:
        rows, provider = ai.extract_references(ref.content_text or "", ref.maker, ref.model)
    except ServiceError as error:
        ref.problem = error.message[:300]
        return
    ref.items, ref.ai_provider = clean_items(rows), provider
    ref.problem = None if ref.items else "AI가 이 자료에서 해석 항목을 찾지 못했습니다."


def register_url(actor: User, url: str, title: str | None = None, maker: str | None = None,
                 model: str | None = None) -> CanReference:
    """공개 자료를 받아 저장하고 AI로 해석 항목 초안을 만든다. 승인 전에는 분석에 쓰지 않는다."""
    url = check_url(url)
    existing = db.session.scalar(select(CanReference.id).where(CanReference.url == url))
    if existing:
        raise ServiceError(f"이미 등록된 자료입니다(참고자료 #{existing}).", 409)
    text, found_title = fetch_text(url)
    if not text.strip():
        raise ServiceError("자료에 글자가 없습니다.")
    ref = CanReference(source_type="url", title=((title or "").strip() or found_title or url)[:200], url=url[:500],
                       maker=(maker or "").strip()[:50] or None, model=(model or "").strip()[:100] or None,
                       keywords=[], status=ReferenceStatus.PENDING, content_text=text, items=[],
                       created_by=actor.id)
    db.session.add(ref)
    db.session.flush()
    _extract(ref)
    audit.record("참고자료 등록", "CanReference", ref.id, user_id=actor.id,
                 changes={"url": url, "items": len(ref.items), "provider": ref.ai_provider})
    db.session.commit()
    return ref


def reextract(actor: User, ref: CanReference, version: int) -> CanReference:
    if ref.version != version:
        raise ServiceError(CONFLICT, 409)
    if ref.source_type != "url" or ref.status != ReferenceStatus.PENDING:
        raise ServiceError("검토 대기 중인 URL 자료만 다시 정리할 수 있습니다.", 409)
    ref = get_reference(ref.id, with_text=True)
    _extract(ref)
    audit.record("참고자료 AI 정리", "CanReference", ref.id, user_id=actor.id,
                 changes={"items": len(ref.items), "provider": ref.ai_provider})
    try:
        db.session.commit()
    except StaleDataError as exc:
        db.session.rollback()
        raise ServiceError(CONFLICT, 409) from exc
    return ref
