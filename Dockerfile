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

# torch arrives with the guardrails, and the wheel PyPI serves on Linux
# bundles the CUDA runtime: roughly three gigabytes of nvidia libraries for a
# container with no GPU to use them. Installing it from PyTorch's CPU index
# first means pip already has it satisfied when the project asks. Nothing here
# needs a GPU: inference is a small classifier over one question at a time.
RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install --upgrade pip \
 && /opt/venv/bin/pip install torch --index-url https://download.pytorch.org/whl/cpu \
 && /opt/venv/bin/pip install .

# ------------------------------------------------------------- runtime stage
FROM python:3.12-slim AS runtime

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONIOENCODING=utf-8 \
    DATA_DIR=/app/data \
    LOG_DIR=/app/logs

# Installed non-editable, the package cannot find the project root by walking
# up from its own file. The paths above make that irrelevant.

RUN useradd --create-home --uid 1000 rag

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY --chown=rag:rag data/ ./data/
RUN mkdir -p /app/logs && chown -R rag:rag /app

USER rag

EXPOSE 8080

HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3     CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8080/health').status==200 else 1)"

# The image serves the API by default. The CLI is still one word away:
#   docker compose run --rm api ask "..."
ENTRYPOINT ["rag"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8080"]
