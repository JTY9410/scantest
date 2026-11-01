"""보안 잠금 상태 감지·키 제공자 인터페이스(C11a–d).

실송신(C11e–f)은 SCAN_SECURITY_UNLOCK과 정당한 자료가 있을 때만 허용하며,
이 패키지에는 키 크래킹·추출·우회 로직이 없다.
"""

from app.modules.scanner.security.provider import (
    MaterialRef,
    SecurityMaterialProvider,
    EmptyProvider,
    StaticTestProvider,
)
from app.modules.scanner.security.status import (
    analyze_security_trace,
    describe_nrc,
    unlock_allowed,
)

__all__ = [
    "MaterialRef", "SecurityMaterialProvider", "EmptyProvider", "StaticTestProvider",
    "analyze_security_trace", "describe_nrc", "unlock_allowed",
]
