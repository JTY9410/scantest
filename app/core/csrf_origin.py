"""Flask-WTF HTTPS CSRF는 Referer만 검사한다.

일부 브라우저·인앱 웹뷰·프라이버시 설정은 same-origin POST에서 Referer를
빼고 Origin만 보낸다. Origin이 현재 호스트와 같으면 Referer를 채워
유효한 로그인·폼 제출이 400으로 깨지지 않게 한다.
"""

from __future__ import annotations

from urllib.parse import urlsplit


class CsrfOriginReferrer:
    def __init__(self, app):
        self.app = app

    def __call__(self, environ, start_response):
        if not environ.get("HTTP_REFERER") and (origin := environ.get("HTTP_ORIGIN")):
            host = environ.get("HTTP_HOST", "")
            parts = urlsplit(origin)
            if host and parts.scheme in {"http", "https"} and parts.netloc == host:
                environ["HTTP_REFERER"] = f"{origin}/"
        return self.app(environ, start_response)
