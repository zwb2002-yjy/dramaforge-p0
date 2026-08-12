FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        espeak-ng \
        ffmpeg \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --gid 10001 dramaforge \
    && useradd --uid 10001 --gid dramaforge --create-home \
        --home-dir /home/dramaforge --shell /usr/sbin/nologin dramaforge

# Keep COPY list in sync with tests/unit/test_dockerfile_context.py
COPY pyproject.toml README.md ./

# Keep dependency installation independent from application source changes.
# The final editable install below is no-deps, so changing app code does not
# redownload Python packages or optional InsightFace code.
RUN python -c "import tomllib; from pathlib import Path; deps = tomllib.loads(Path('pyproject.toml').read_text())['project']['dependencies']; Path('/tmp/requirements.txt').write_text('\\n'.join(deps) + '\\n')" \
    && pip install --upgrade pip \
    && pip install -r /tmp/requirements.txt \
    && pip install "requests>=2.28,<3" "tqdm>=4.66,<5"

# InsightFace does not publish a CPython 3.12 wheel. Build the official source
# distribution so FaceAnalysis can import its bundled Cython face3d extension.
RUN pip install --no-deps insightface==0.7.3

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
