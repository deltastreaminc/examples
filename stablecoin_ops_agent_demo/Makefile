SHELL := /bin/zsh

IMAGE_NAME ?= public.ecr.aws/i3m5v2n6/deltastreaminc/stablecoin-ops-agent-demo:latest
CONTAINER_NAME ?= stablecoin-ops-agent
VENV_DIR ?= .venv
PYTHON ?= $(VENV_DIR)/bin/python
PIP ?= $(VENV_DIR)/bin/pip

.PHONY: install dev run build-image push-image run-image stop-image health frontend-build backend-check

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

build-image:
	docker build -f backend/Dockerfile -t $${IMAGE_NAME:-$(IMAGE_NAME)} .

push-image:
	docker push $${IMAGE_NAME:-$(IMAGE_NAME)}

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
