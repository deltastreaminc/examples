FROM node:20-bookworm-slim AS frontend-build

WORKDIR /frontend

COPY frontend/package.json /frontend/package.json
COPY frontend/tsconfig.json /frontend/tsconfig.json
COPY frontend/tsconfig.node.json /frontend/tsconfig.node.json
COPY frontend/vite.config.ts /frontend/vite.config.ts
COPY frontend/index.html /frontend/index.html
COPY frontend/src /frontend/src

# The frontend is built with a relative base; the serving path is chosen at
# runtime from ROOT_PATH (injected into index.html by the backend). No build arg.
RUN npm install
RUN npm run build

FROM python:3.12-slim-bookworm AS python-build

WORKDIR /app

COPY backend/requirements.txt /app/requirements.txt
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir --upgrade pip \
    && /opt/venv/bin/pip install --no-cache-dir -r /app/requirements.txt

FROM python:3.12-slim-bookworm

ARG BUILD_DATE=unknown
ARG BUILD_MARKER=local

ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    BUILD_DATE=${BUILD_DATE} \
    BUILD_MARKER=${BUILD_MARKER}

WORKDIR /app

# Apply available Debian security fixes in the runtime layer and remove package
# manager state. Pinning Bookworm avoids the vulnerable util-linux/perl/ncurses
# package set reported from newer slim variants while upstream fixes are pending.
RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --home-dir /app --shell /usr/sbin/nologin app

COPY --from=python-build /opt/venv /opt/venv
COPY backend/app /app/app
COPY --from=frontend-build /frontend/dist /app/frontend/dist

RUN chown -R app:app /app

USER 10001:10001

EXPOSE 8000

# Set ROOT_PATH to the path prefix the app is served under when the Ingress does
# not strip it (e.g. -e ROOT_PATH=/polymarket). Leave unset to serve at root
# (local Docker). The frontend base path is derived from this at runtime.
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
