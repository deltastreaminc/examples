SHELL := /bin/zsh

IMAGE_NAME ?= public.ecr.aws/i3m5v2n6/deltastreaminc/polymarket-live-signal-radar-demo:latest
CONTAINER_NAME ?= polymarket-live-signal-radar
PLATFORMS ?= linux/amd64,linux/arm64
LOCAL_PLATFORM ?= linux/arm64
BUILDER_NAME ?= polymarket-multiarch
ECR_PUBLIC_REGION ?= us-east-1
VENV_DIR ?= .venv
PYTHON ?= $(VENV_DIR)/bin/python
PIP ?= $(VENV_DIR)/bin/pip

.PHONY: install dev run ecr-login buildx-builder build-image build-image-local push-image run-image stop-image health frontend-build backend-check dsql-list

install:
	python3 -m venv $(VENV_DIR)
	PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1 $(PIP) install -r backend/requirements.txt
	npm --prefix frontend install

run:
	$(PYTHON) -m uvicorn app.main:app --host $${BACKEND_HOST:-0.0.0.0} --port $${BACKEND_PORT:-8000} --app-dir backend

dev:
	@zsh -c 'set -euo pipefail; trap "kill 0" EXIT; \
		$(PYTHON) -m uvicorn app.main:app --host $${BACKEND_HOST:-0.0.0.0} --port $${BACKEND_PORT:-8000} --app-dir backend --reload & \
		npm --prefix frontend run dev -- --host --port $${FRONTEND_PORT:-5173} & \
		wait'

buildx-builder:
	@docker buildx inspect $${BUILDER_NAME:-$(BUILDER_NAME)} >/dev/null 2>&1 || docker buildx create --name $${BUILDER_NAME:-$(BUILDER_NAME)} --driver docker-container --use
	docker buildx inspect $${BUILDER_NAME:-$(BUILDER_NAME)} --bootstrap

ecr-login:
	aws ecr-public get-login-password --region $${ECR_PUBLIC_REGION:-$(ECR_PUBLIC_REGION)} | docker login --username AWS --password-stdin public.ecr.aws

build-image: ecr-login buildx-builder
	docker buildx build --builder $${BUILDER_NAME:-$(BUILDER_NAME)} --platform $${PLATFORMS:-$(PLATFORMS)} -f backend/Dockerfile -t $${IMAGE_NAME:-$(IMAGE_NAME)} --push .

build-image-local: buildx-builder
	docker buildx build --builder $${BUILDER_NAME:-$(BUILDER_NAME)} --platform $${LOCAL_PLATFORM:-$(LOCAL_PLATFORM)} -f backend/Dockerfile -t $${IMAGE_NAME:-$(IMAGE_NAME)} --load .

push-image:
	@printf 'Multi-arch images are pushed during make build-image\n'

run-image:
	docker run --rm --name $${CONTAINER_NAME:-$(CONTAINER_NAME)} -p $${BACKEND_PORT:-8000}:8000 $${IMAGE_NAME:-$(IMAGE_NAME)}

stop-image:
	-docker stop $${CONTAINER_NAME:-$(CONTAINER_NAME)}

health:
	curl -sS http://localhost:$${BACKEND_PORT:-8000}/api/health

frontend-build:
	npm --prefix frontend run build

backend-check:
	$(PYTHON) -m compileall backend/app

dsql-list:
	@printf '%s\n' dsql/01_sources.sql dsql/02_normalization.sql dsql/03_metadata.sql dsql/04_flow_windows.sql dsql/05_signal_context.sql dsql/06_materialized_views.sql
