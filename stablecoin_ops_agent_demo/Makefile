SHELL := /bin/zsh

IMAGE_NAME ?= public.ecr.aws/i3m5v2n6/deltastreaminc/stablecoin-ops-agent-demo:latest
CONTAINER_NAME ?= stablecoin-ops-agent
PLATFORMS ?= linux/amd64,linux/arm64
BUILDX_BUILDER ?= stablecoin-multiarch
VENV_DIR ?= .venv
PYTHON ?= $(VENV_DIR)/bin/python
PIP ?= $(VENV_DIR)/bin/pip

.PHONY: install dev run build-image buildx-ensure build-image-multiarch push-image push-image-multiarch run-image stop-image health frontend-build backend-check

install:
	python3 -m venv $(VENV_DIR)
	PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1 $(PIP) install -r backend/requirements.txt
	$(PIP) install -r datagen/requirements.txt
	npm --prefix frontend install

run:
	$(PYTHON) -m uvicorn app.main:app --host $${BACKEND_HOST:-0.0.0.0} --port $${BACKEND_PORT:-8000} --app-dir backend

dev:
	@zsh -c 'set -euo pipefail; trap "kill 0" EXIT; \
		$(PYTHON) -m uvicorn app.main:app --host $${BACKEND_HOST:-0.0.0.0} --port $${BACKEND_PORT:-8000} --app-dir backend --reload & \
		npm --prefix frontend run dev -- --host --port $${FRONTEND_PORT:-5173} & \
		wait'

build-image:
	docker build -f backend/Dockerfile -t $${IMAGE_NAME:-$(IMAGE_NAME)} .

buildx-ensure:
	@if ! docker buildx inspect $${BUILDX_BUILDER:-$(BUILDX_BUILDER)} >/dev/null 2>&1; then \
		docker buildx create --name $${BUILDX_BUILDER:-$(BUILDX_BUILDER)} --driver docker-container --use; \
	fi
	docker buildx use $${BUILDX_BUILDER:-$(BUILDX_BUILDER)}
	docker buildx inspect --bootstrap

build-image-multiarch: buildx-ensure
	docker buildx build --platform $${PLATFORMS:-$(PLATFORMS)} -f backend/Dockerfile -t $${IMAGE_NAME:-$(IMAGE_NAME)} --push .

push-image:
	docker push $${IMAGE_NAME:-$(IMAGE_NAME)}

push-image-multiarch:
	docker buildx imagetools inspect $${IMAGE_NAME:-$(IMAGE_NAME)}

run-image:
	docker run --rm --name $${CONTAINER_NAME:-$(CONTAINER_NAME)} -p $${BACKEND_PORT:-8000}:8000 --env-file .env $${IMAGE_NAME:-$(IMAGE_NAME)}

stop-image:
	-docker stop $${CONTAINER_NAME:-$(CONTAINER_NAME)}

health:
	curl -sS http://localhost:$${BACKEND_PORT:-8000}/api/health

frontend-build:
	npm --prefix frontend run build

backend-check:
	$(PYTHON) -m compileall backend/app

.PHONY: datagen-install datagen-run datagen-run-once datagen-reset-state datagen-check dsql-list

datagen-install:
	$(PIP) install -r datagen/requirements.txt

datagen-run:
	$(PYTHON) -m datagen.main

datagen-run-once:
	$(PYTHON) -m datagen.main --max-events 1

datagen-reset-state:
	rm -f .stablecoin-payment-demo-state.json

datagen-check:
	$(PYTHON) -m compileall datagen

dsql-list:
	@printf '%s\n' dsql/01_database.sql dsql/02_sources.sql dsql/03_transfer_pipeline.sql dsql/04_invoice_enrichment_pipeline.sql dsql/05_final_context_changelog.sql dsql/06_materialized_views.sql dsql/09_grants.sql dsql/10_query_tags.sql dsql/07_validation_queries.sql dsql/08_demo_queries.sql

.PHONY: dsql-teardown

dsql-teardown:
	./scripts/teardown_demo.sh
