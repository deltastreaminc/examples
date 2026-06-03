FROM node:20-bookworm-slim AS frontend-build

WORKDIR /frontend

COPY frontend/package.json /frontend/package.json
COPY frontend/package-lock.json /frontend/package-lock.json
COPY frontend/tsconfig.json /frontend/tsconfig.json
COPY frontend/tsconfig.node.json /frontend/tsconfig.node.json
COPY frontend/vite.config.ts /frontend/vite.config.ts
COPY frontend/index.html /frontend/index.html
COPY frontend/src /frontend/src

RUN npm ci
RUN npm run build

FROM python:3.12-slim

WORKDIR /app

COPY backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY backend/app /app/app
COPY --from=frontend-build /frontend/dist /app/frontend/dist

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
