# --------------------------------------------------------------- build stage
# Dependencies are installed into a self-contained virtualenv so the runtime
# image can take the result and leave the build toolchain behind.
FROM python:3.12-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build

# pyproject declares README.md as the long description, so the build fails
# without it. Copying manifests before the source keeps this layer cached
# across code changes.
COPY pyproject.toml README.md ./
COPY src/ ./src/

RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install --upgrade pip \
 && /opt/venv/bin/pip install .

# ------------------------------------------------------------- runtime stage
FROM python:3.12-slim AS runtime

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONIOENCODING=utf-8 \
    DATA_DIR=/app/data \
    VECTOR_STORE_DIR=/app/.chroma \
    LOG_DIR=/app/logs

# Installed non-editable, the package cannot find the project root by walking
# up from its own file. The paths above make that irrelevant.

RUN useradd --create-home --uid 1000 rag

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY --chown=rag:rag data/ ./data/
RUN mkdir -p /app/.chroma /app/logs && chown -R rag:rag /app

USER rag

# The image is the CLI: `docker compose run --rm rag ask "..."`.
ENTRYPOINT ["rag"]
CMD ["status"]
