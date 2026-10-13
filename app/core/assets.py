import hashlib
from pathlib import Path

from flask import Flask

# 내용이 바뀌면 브라우저·service worker 캐시를 새로 받아야 하는 정적 파일
VERSIONED_FILES = ("dist/app.css", "js/app.js", "js/components/pwa.js", "service-worker.js")


def asset_version(app: Flask) -> str:
    """정적 파일 내용으로 만든 캐시 버전. 운영에서는 한 번만 계산하고, 개발에서는 매번 다시 계산한다."""
    cached = app.extensions.get("asset_version")
    if cached and not app.debug:
        return cached
    digest = hashlib.sha1(app.config["APP_VERSION"].encode())
    for name in VERSIONED_FILES:
        path = Path(app.static_folder, name)
        if path.exists():
            digest.update(path.read_bytes())
    value = digest.hexdigest()[:10]
    app.extensions["asset_version"] = value
    return value
