from typing import Any


class ServiceError(Exception):
    """업무 규칙 위반. API는 그대로 JSON 오류로, 관리자 화면은 안내 메시지로 보여준다."""

    def __init__(self, message: str, status: int = 400, **extra: Any):
        super().__init__(message)
        self.message = message
        self.status = status
        self.extra = extra
