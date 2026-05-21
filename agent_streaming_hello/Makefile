IMAGE_NAME ?= deltastream-hello-world-agent
IMAGE_TAG ?= latest
CONTAINER_NAME ?= deltastream-hello-world-agent-app
PORT ?= 8501
PYTHON ?= python3
VENV_DIR ?= .venv
VENV_PYTHON := $(VENV_DIR)/bin/python

KAFKA_BROKERS ?=
KAFKA_USERNAME ?=
KAFKA_PASSWORD ?=
ANTHROPIC_API_KEY ?=
DELTASTREAM_API_TOKEN ?=
DELTASTREAM_API_URL ?=
DELTASTREAM_MCP_URL ?=
ANTHROPIC_MODEL ?=

.PHONY: help venv install run clean clean-cache docker-build docker-run docker-run-detached docker-stop

help:
	@printf "Targets:\n"
	@printf "  venv                 Create local virtual environment (.venv)\n"
	@printf "  install              Install Python dependencies\n"
	@printf "  run                  Run Streamlit locally\n"
	@printf "  clean                Remove local build/dependency artifacts\n"
	@printf "  clean-cache          Remove caches without deleting .venv\n"
	@printf "  docker-build         Build Docker image\n"
	@printf "  docker-build-local   Build single-platform image with buildx\n"
	@printf "  docker-build-multi   Build multi-platform image and push\n"
	@printf "  docker-run           Run Docker container in foreground\n"
	@printf "  docker-run-detached  Run Docker container in background\n"
	@printf "  docker-stop          Stop and remove Docker container\n"

venv:
	$(PYTHON) -m venv $(VENV_DIR)

install: venv
	$(VENV_PYTHON) -m pip install --upgrade pip
	$(VENV_PYTHON) -m pip install -r requirements.txt

run:
	KAFKA_BROKERS="$(KAFKA_BROKERS)" KAFKA_USERNAME="$(KAFKA_USERNAME)" KAFKA_PASSWORD="$(KAFKA_PASSWORD)" ANTHROPIC_API_KEY="$(ANTHROPIC_API_KEY)" DELTASTREAM_API_TOKEN="$(DELTASTREAM_API_TOKEN)" DELTASTREAM_API_URL="$(DELTASTREAM_API_URL)" DELTASTREAM_MCP_URL="$(DELTASTREAM_MCP_URL)" ANTHROPIC_MODEL="$(ANTHROPIC_MODEL)" $(VENV_PYTHON) -m streamlit run app.py --server.port $(PORT)

clean:
	rm -rf .venv
	$(MAKE) clean-cache

clean-cache:
	rm -rf build dist *.egg-info
	rm -rf __pycache__ src/__pycache__
	rm -rf .pytest_cache .mypy_cache .ruff_cache
	rm -f .coverage

docker-build:
	docker build -t $(IMAGE_NAME):$(IMAGE_TAG) .

docker-build-local:
	docker buildx build --platform linux/arm64 -t $(IMAGE_NAME):$(IMAGE_TAG) --load .

docker-build-multi:
	docker buildx build --platform linux/amd64,linux/arm64 -t $(IMAGE_NAME):$(IMAGE_TAG) --push .

docker-run:
	docker run --rm -it --name $(CONTAINER_NAME) -p $(PORT):8501 $(IMAGE_NAME):$(IMAGE_TAG)

docker-run-detached:
	docker run -d --rm --name $(CONTAINER_NAME) -p $(PORT):8501 $(IMAGE_NAME):$(IMAGE_TAG)

docker-stop:
	-docker stop $(CONTAINER_NAME)
