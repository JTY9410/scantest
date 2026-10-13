# syntax=docker/dockerfile:1.7

# 1) 관리자 화면 CSS(Tailwind) 빌드
FROM node:24-slim AS assets
WORKDIR /build
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY app/static ./app/static
COPY app/templates ./app/templates
RUN npm run build:css

# 2) 파이썬 공통 기반
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    FLASK_APP=app.wsgi
WORKDIR /srv
RUN groupadd --system app && useradd --system --gid app --home-dir /srv --no-create-home app
COPY requirements.lock ./
RUN pip install -r requirements.lock

# 3) 개발용: 소스는 compose에서 마운트한다.
FROM base AS dev
COPY requirements-dev.lock ./
RUN pip install -r requirements-dev.lock
USER app
EXPOSE 8000
CMD ["flask", "run", "--host", "0.0.0.0", "--port", "8000", "--debug"]

# 4) 운영용: 소스와 빌드된 CSS만 담고 비밀값은 넣지 않는다. 시작 시 DB 이전을 자동 실행하지 않는다.
FROM base AS prod
ARG APP_VERSION=2.0.0
ENV APP_ENV=production \
    APP_VERSION=${APP_VERSION}
COPY --chown=app:app app ./app
COPY --chown=app:app migrations ./migrations
COPY --chown=app:app gunicorn.conf.py pyproject.toml ./
COPY --from=assets --chown=app:app /build/app/static/dist ./app/static/dist
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/up', timeout=4)"]
CMD ["gunicorn", "-c", "gunicorn.conf.py", "app.wsgi:app"]
