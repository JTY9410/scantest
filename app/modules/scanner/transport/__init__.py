"""차량 진단 전송 계층 추상화.

모든 연결 방식(CAN/ELM327, DoIP, J2534)에 대해 동일한 인터페이스를 제공하여
스캔 계획·해석·리포트가 전송 방식에 무관하게 동작하도록 합니다.
"""

from app.modules.scanner.transport.base import TransportAdapter, TransportError, TransportResult
from app.modules.scanner.transport.can import CanAdapter
from app.modules.scanner.transport.doip import DoIPAdapter
from app.modules.scanner.transport.j2534 import J2534Adapter

__all__ = [
    "TransportAdapter",
    "TransportError",
    "TransportResult",
    "CanAdapter",
    "DoIPAdapter",
    "J2534Adapter",
]
