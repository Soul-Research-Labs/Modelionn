# ── Stage 0: Rust prover build ───────────────────────────────
FROM rust:1.78-slim-bookworm AS prover-builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    pkg-config libssl-dev cmake build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /prover
COPY prover/Cargo.toml prover/Cargo.lock* ./
COPY prover/src/ src/

# Build the prover library (release mode, default features only for base image)
RUN cargo build --release --lib 2>/dev/null || true
# The compiled .so will be at /prover/target/release/libmodelio_prover.so (if available)

# ── Stage 1: Python backend ──────────────────────────────────
FROM python:3.11-slim AS backend

WORKDIR /app
COPY pyproject.toml README.md ./
RUN pip install --no-cache-dir --upgrade pip
COPY registry/ registry/
COPY subnet/ subnet/
COPY evaluation/ evaluation/
COPY sdk/ sdk/
COPY cli/ cli/
COPY prover/python/ prover/python/

RUN pip install --no-cache-dir .

# Copy compiled Rust prover library if build succeeded
RUN --mount=from=prover-builder,source=/prover/target/release,target=/tmp/prover-build \
    cp /tmp/prover-build/*.so /usr/local/lib/ 2>/dev/null; \
    ldconfig || true

# ── Stage 2: Frontend build (optional, for standalone) ───────
FROM node:20-alpine AS frontend

WORKDIR /web
COPY web/package.json web/package-lock.json* ./
RUN npm ci --ignore-scripts
COPY web/ .
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

# ── Stage 3: Final image ────────────────────────────────────
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd -r modelionn && useradd -r -g modelionn -m modelionn

WORKDIR /app
COPY --from=backend /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=backend /usr/local/bin/uvicorn /usr/local/bin/celery /usr/local/bin/
COPY --from=backend /app /app

# Copy Rust prover shared library if available
RUN --mount=from=backend,source=/usr/local/lib,target=/tmp/backend-lib \
    cp /tmp/backend-lib/*.so /usr/local/lib/ 2>/dev/null; \
    ldconfig || true

COPY docker/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# Copy standalone Next.js output (for single-container deploys)
COPY --from=frontend /web/.next/standalone /app/web-standalone
COPY --from=frontend /web/.next/static /app/web-standalone/.next/static
COPY --from=frontend /web/public /app/web-standalone/public

# Writable data directory
RUN mkdir -p /app/data && chown -R modelionn:modelionn /app/data

USER modelionn

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -sf http://localhost:8000/health || exit 1

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["uvicorn", "registry.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
