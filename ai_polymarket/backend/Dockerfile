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

FROM python:3.12-slim

WORKDIR /app

COPY backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY backend/app /app/app
COPY --from=frontend-build /frontend/dist /app/frontend/dist

EXPOSE 8000

# Set ROOT_PATH to the path prefix the app is served under when the Ingress does
# not strip it (e.g. -e ROOT_PATH=/polymarket). Leave unset to serve at root
# (local Docker). The frontend base path is derived from this at runtime.
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
