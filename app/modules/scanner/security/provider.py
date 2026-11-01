"""주입형 보안 자료 제공자. 앱은 자료를 계산·추출하지 않고 전달만 한다."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class MaterialRef:
    """로그·감사에 남을 요약. 원문 바이트는 넣지 않는다."""
    kind: str  # "seed_key" | "certificate" | "test"
    level: int
    size: int
    source: str


class SecurityMaterialProvider(Protocol):
    def has_material(self, level: int) -> bool: ...

    def request_seed_key(self, level: int, seed: bytes) -> tuple[bytes, MaterialRef]:
        """권한자가 주입한 seed→key 결과. 미구현·자료 없으면 예외."""
        ...

    def sign_challenge(self, level: int, challenge: bytes) -> tuple[bytes, MaterialRef]:
        """인증서형 41/42용 서명 응답. 서명키는 제공자 밖(볼트·제조사 도구)."""
        ...


class EmptyProvider:
    """자료 없음. 실송신 경로에서 송신 0을 보장한다."""

    def has_material(self, level: int) -> bool:
        return False

    def request_seed_key(self, level: int, seed: bytes) -> tuple[bytes, MaterialRef]:
        raise LookupError("정당한 보안 자료가 없습니다(seed/key).")

    def sign_challenge(self, level: int, challenge: bytes) -> tuple[bytes, MaterialRef]:
        raise LookupError("정당한 보안 자료가 없습니다(인증서·서명).")


class StaticTestProvider:
    """모의 ECU 전용. 고정 테스트 벡터만 허용(실차 키 아님)."""

    def __init__(self, keys: dict[int, bytes] | None = None, signatures: dict[int, bytes] | None = None):
        self._keys = dict(keys or {})
        self._signatures = dict(signatures or {})

    def has_material(self, level: int) -> bool:
        return level in self._keys or level in self._signatures

    def request_seed_key(self, level: int, seed: bytes) -> tuple[bytes, MaterialRef]:
        if level not in self._keys:
            raise LookupError("테스트 seed/key 없음")
        key = self._keys[level]
        return key, MaterialRef("test", level, len(key), "StaticTestProvider")

    def sign_challenge(self, level: int, challenge: bytes) -> tuple[bytes, MaterialRef]:
        if level not in self._signatures:
            raise LookupError("테스트 서명 없음")
        sig = self._signatures[level]
        return sig, MaterialRef("test", level, len(sig), "StaticTestProvider")
