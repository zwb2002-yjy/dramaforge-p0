FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

ARG INSIGHTFACE_MODEL_URL=https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_l.zip

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        espeak-ng \
        ffmpeg \
        unzip \
    && rm -rf /var/lib/apt/lists/*

# Keep COPY list in sync with tests/unit/test_dockerfile_context.py
COPY pyproject.toml README.md ./

# Keep dependency installation independent from application source changes.
# The final editable install below is no-deps, so changing app code does not
# redownload Python packages, InsightFace, or the buffalo_l model.
RUN python -c "import tomllib; from pathlib import Path; deps = tomllib.loads(Path('pyproject.toml').read_text())['project']['dependencies']; Path('/tmp/requirements.txt').write_text('\\n'.join(deps) + '\\n')" \
    && pip install --upgrade pip \
    && pip install -r /tmp/requirements.txt \
    && pip install "requests>=2.28,<3" "tqdm>=4.66,<5"

# InsightFace does not publish a CPython 3.12 wheel. Build the official source
# distribution so FaceAnalysis can import its bundled Cython face3d extension.
RUN pip install --no-deps insightface==0.7.3

# Keep the formal CPU face-consistency runtime inside the image.  The model is
# downloaded during the build so a container never falls back to an implicit
# network download while processing a production job.
RUN --mount=type=cache,target=/var/cache/dramaforge-insightface \
    mkdir -p /root/.insightface/models/buffalo_l \
    && if [ ! -f /var/cache/dramaforge-insightface/buffalo_l.zip ]; then \
        curl --fail --location --retry 3 --retry-delay 2 "$INSIGHTFACE_MODEL_URL" \
            --output /var/cache/dramaforge-insightface/buffalo_l.zip; \
    fi \
    && cp /var/cache/dramaforge-insightface/buffalo_l.zip /tmp/buffalo_l.zip \
    && unzip -q /tmp/buffalo_l.zip -d /root/.insightface/models/buffalo_l \
    && rm /tmp/buffalo_l.zip \
    && test -f /root/.insightface/models/buffalo_l/w600k_r50.onnx \
    && ffmpeg -version >/dev/null \
    && espeak-ng --version >/dev/null

# Keep this in a separate layer so an initialization failure reports its Python
# traceback while the downloaded model remains cacheable for the next build.
RUN python -c "from insightface.app import FaceAnalysis; app = FaceAnalysis(name='buffalo_l', providers=['CPUExecutionProvider']); app.prepare(ctx_id=-1); print('insightface_cpu_ready')"

COPY app ./app
COPY alembic.ini ./
COPY alembic ./alembic

RUN pip install --no-deps -e .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
