FROM python:3.12-slim

ARG DRAMAFORGE_VERSION=0.1.0
ARG DRAMAFORGE_SOURCE_COMMIT=local

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# Keep successfully downloaded archives across BuildKit retries.  The explicit
# single access queue and disabled HTTP pipelining avoid overwhelming common
# desktop/CI proxies; the outer loop recovers when a mirror still returns a
# transient 5xx after APT's per-file retries.
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt/lists,sharing=locked \
    set -eux; \
    sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources; \
    apt_options="-o Acquire::Retries=10 -o Acquire::Queue-Mode=access -o Acquire::http::Pipeline-Depth=0 -o Acquire::http::Timeout=60 -o Binary::apt::APT::Keep-Downloaded-Packages=true"; \
    apt-get ${apt_options} update; \
    attempt=1; \
    while ! apt-get ${apt_options} install -y --no-install-recommends \
        build-essential \
        curl \
        espeak-ng \
        ffmpeg \
        postgresql-client; do \
        if [ "${attempt}" -ge 3 ]; then exit 1; fi; \
        attempt=$((attempt + 1)); \
        apt-get ${apt_options} update; \
    done

RUN groupadd --gid 10001 dramaforge \
    && useradd --uid 10001 --gid dramaforge --create-home \
        --home-dir /home/dramaforge --shell /usr/sbin/nologin dramaforge

# Keep COPY list in sync with tests/unit/test_dockerfile_context.py
COPY pyproject.toml uv.lock README.md ./

# Export exact versions and hashes from the committed lock.  Application source
# changes then reuse this dependency layer, while release images cannot drift to
# newer packages merely because a version range still matches.
RUN pip install --upgrade pip "uv==0.12.0" \
    && uv export --frozen --no-dev --no-emit-project --output-file /tmp/requirements.txt \
    && pip install -r /tmp/requirements.txt \
    && pip uninstall -y uv

# Compilers are build-time tools only; keep them out of the runtime image.
RUN apt-get purge -y --auto-remove build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN ffmpeg -version >/dev/null \
    && espeak-ng --version >/dev/null

# Release identity belongs after dependency layers so a new source commit does
# not invalidate the expensive APT and locked Python dependency caches.
LABEL org.opencontainers.image.title="DramaForge backend" \
      org.opencontainers.image.version=$DRAMAFORGE_VERSION \
      org.opencontainers.image.revision=$DRAMAFORGE_SOURCE_COMMIT \
      org.opencontainers.image.source="https://github.com/zwb2002-yjy/DramaForge"

ENV DRAMAFORGE_SOURCE_COMMIT=$DRAMAFORGE_SOURCE_COMMIT

COPY --chown=dramaforge:dramaforge app ./app
COPY --chown=dramaforge:dramaforge alembic.ini ./
COPY --chown=dramaforge:dramaforge alembic ./alembic

RUN pip install --no-deps -e .

USER 10001:10001

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
