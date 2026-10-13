import os

bind = f"0.0.0.0:{os.environ.get('PORT', '8000')}"
workers = int(os.environ.get("WEB_CONCURRENCY", "3"))
threads = int(os.environ.get("GUNICORN_THREADS", "2"))
timeout = 60
graceful_timeout = 30
accesslog = "-"
errorlog = "-"
# 요청 URL의 쿼리(토큰·키가 들어올 수 있음)는 접근 로그에 남기지 않는다.
access_log_format = '%(h)s "%(m)s %(U)s" %(s)s %(b)s %(L)ss'
