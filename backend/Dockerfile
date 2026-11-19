# Local ASR build stage: fixed whisper.cpp tag plus the frozen multilingual model.
# The model bytes are verified by SHA-256 before they enter any runtime image; an
# unreachable or different artifact fails the build instead of silently degrading.
FROM python:3.14-slim-bookworm AS whisper

ENV DEBIAN_FRONTEND=noninteractive

RUN set -eux; \
    sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources; \
    apt-get update; \
    apt-get install -y --no-install-recommends build-essential cmake curl ca-certificates; \
    rm -rf /var/lib/apt/lists/*

ARG WHISPER_SOURCE_URL=https://codeload.github.com/ggml-org/whisper.cpp/tar.gz/refs/tags/v1.9.5
ARG WHISPER_MODEL_SHA256=60ed5bc3dd14eea856493d334349b405782ddcaf0028d4b5df4088345fba2efe
ARG WHISPER_MODEL_URLS="https://huggingface.co/ggerganov/whisper.cpp/resolve/5359861c739e955e79d9a303bcbc70fb988958b1/ggml-base.bin https://hf-mirror.com/ggerganov/whisper.cpp/resolve/5359861c739e955e79d9a303bcbc70fb988958b1/ggml-base.bin"

RUN set -eux; \
    mkdir -p /src; \
    curl -fsSL --retry 5 --retry-delay 3 --max-time 900 -o /src/whisper.tar.gz "$WHISPER_SOURCE_URL"; \
    tar -xzf /src/whisper.tar.gz -C /src; \
    mv /src/whisper.cpp-* /src/whisper; \
    cmake -S /src/whisper -B /src/build -DCMAKE_BUILD_TYPE=Release \
        -DBUILD_SHARED_LIBS=OFF -DWHISPER_BUILD_TESTS=OFF -DWHISPER_BUILD_EXAMPLES=ON \
        -DWHISPER_BUILD_SERVER=OFF; \
    cmake --build /src/build --target whisper-cli -j"$(nproc)"; \
    install -m 0755 /src/build/bin/whisper-cli /usr/local/bin/whisper-cli

RUN set -eux; \
    mkdir -p /opt/whisper; \
    for url in $WHISPER_MODEL_URLS; do \
        if curl -fsSL --retry 2 --retry-delay 5 --connect-timeout 15 --max-time 900 -o /opt/whisper/ggml-base.bin "$url"; then \
            break; \
        fi; \
        rm -f /opt/whisper/ggml-base.bin; \
    done; \
    test -s /opt/whisper/ggml-base.bin; \
    echo "$WHISPER_MODEL_SHA256  /opt/whisper/ggml-base.bin" | sha256sum -c -

# Pin Debian Bookworm so the bundled PostgreSQL client stays on major 15,
# matching the PostgreSQL 15 service used by the release Compose topology.
# An unqualified ``python:3.14-slim`` may advance to a newer Debian release
# and create a pg_dump/pg_restore format mismatch during backup recovery.
FROM python:3.14-slim-bookworm

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DRAMAFORGE_WHISPER_CLI=/usr/local/bin/whisper-cli \
    DRAMAFORGE_WHISPER_MODEL=/opt/whisper/ggml-base.bin \
    DRAMAFORGE_WHISPER_MODEL_SHA256=60ed5bc3dd14eea856493d334349b405782ddcaf0028d4b5df4088345fba2efe \
    DRAMAFORGE_WHISPER_VERSION=v1.9.5 \
    DRAMAFORGE_WHISPER_THREADS=4

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
        fonts-noto-cjk \
        ffmpeg \
        git \
        libgomp1 \
        postgresql-client \
        poppler-utils \
        tesseract-ocr \
        tesseract-ocr-chi-sim \
        tesseract-ocr-chi-tra \
        tesseract-ocr-eng \
        iptables; do \
        if [ "${attempt}" -ge 3 ]; then exit 1; fi; \
        attempt=$((attempt + 1)); \
        apt-get ${apt_options} update; \
    done

COPY --from=whisper /usr/local/bin/whisper-cli /usr/local/bin/whisper-cli
COPY --from=whisper /opt/whisper/ggml-base.bin /opt/whisper/ggml-base.bin

RUN groupadd --gid 10001 dramaforge \
    && useradd --uid 10001 --gid dramaforge --create-home \
        --home-dir /home/dramaforge --shell /usr/sbin/nologin dramaforge

# Keep COPY list in sync with tests/unit/test_dockerfile_context.py
COPY pyproject.toml uv.lock README.md ./

# Export exact versions and hashes from the committed lock.  Application source
# changes then reuse this dependency layer, while release images cannot drift to
# newer packages merely because a version range still matches.
RUN pip install --upgrade pip "uv==0.13.3" \
    && uv export --frozen --no-dev --no-emit-project --output-file /tmp/requirements.txt \
    && pip install -r /tmp/requirements.txt \
    && pip uninstall -y uv

# Compilers are build-time tools only; keep them out of the runtime image.
RUN apt-get purge -y --auto-remove build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN ffmpeg -version >/dev/null \
    && espeak-ng --version >/dev/null \
    && command -v pdftotext >/dev/null \
    && command -v tesseract >/dev/null \
    && tesseract --list-langs 2>/dev/null | grep -qx chi_sim \
    && whisper-cli --help 2>&1 | grep -q 'usage: whisper-cli' \
    && test -s /opt/whisper/ggml-base.bin

# Release identity belongs after dependency layers so a new source commit does
# not invalidate the expensive APT and locked Python dependency caches.
ARG DRAMAFORGE_VERSION=0.1.0
ARG DRAMAFORGE_SOURCE_COMMIT=local

LABEL org.opencontainers.image.title="DramaForge backend" \
      org.opencontainers.image.version=$DRAMAFORGE_VERSION \
      org.opencontainers.image.revision=$DRAMAFORGE_SOURCE_COMMIT \
      org.opencontainers.image.source="https://github.com/zwb2002-yjy/dramaforge-p0"

ENV DRAMAFORGE_SOURCE_COMMIT=$DRAMAFORGE_SOURCE_COMMIT

COPY --chown=dramaforge:dramaforge app ./app
COPY --chown=dramaforge:dramaforge alembic.ini ./
COPY --chown=dramaforge:dramaforge alembic ./alembic

RUN pip install --no-deps -e .

USER 10001:10001

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--no-proxy-headers"]
