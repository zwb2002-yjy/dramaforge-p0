FROM python:3.12-slim

ARG DRAMAFORGE_VERSION=0.1.0
ARG DRAMAFORGE_SOURCE_COMMIT=local

LABEL org.opencontainers.image.title="DramaForge backend" \
      org.opencontainers.image.version=$DRAMAFORGE_VERSION \
      org.opencontainers.image.revision=$DRAMAFORGE_SOURCE_COMMIT \
      org.opencontainers.image.source="https://github.com/zwb2002-yjy/DramaForge"

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DRAMAFORGE_SOURCE_COMMIT=$DRAMAFORGE_SOURCE_COMMIT

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        espeak-ng \
        ffmpeg \
        postgresql-client \
    && rm -rf /var/lib/apt/lists/*

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

# The optional InsightFace Python runtime is present, but pretrained weights are
# neither downloaded nor bundled.  A deployer must separately obtain licensed
# model files, mount them, and explicitly enable INSIGHTFACE_ENABLED.
RUN ffmpeg -version >/dev/null \
    && espeak-ng --version >/dev/null

COPY --chown=dramaforge:dramaforge app ./app
COPY --chown=dramaforge:dramaforge alembic.ini ./
COPY --chown=dramaforge:dramaforge alembic ./alembic

RUN pip install --no-deps -e .

USER 10001:10001

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
