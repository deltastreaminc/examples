IMAGE_NAME ?= deltastream-agent-signup-chat-starter
IMAGE_TAG ?= latest
CONTAINER_NAME ?= deltastream-agent-signup-chat-starter-app
PORT ?= 8501
PYTHON ?= python3
VENV_DIR ?= .venv
VENV_PYTHON := $(VENV_DIR)/bin/python

API_TOKEN ?=
SIGNUP_API_URL ?= https://demo.local.deltastream.io/api/signup
ANTHROPIC_BASE_URL ?= https://demo.local.deltastream.io/anthropic/
DELTASTREAM_MCP_URL ?= https://api-kd8j38.stage.deltastream-internal.name/mcp/v2
INSECURE_DEMO_TLS ?= true
DOCKER_EXTRA_ARGS ?=
DEMO_HOST_IP ?=
API_HOST_IP ?=

DOCKER_HOST_MAP_ARGS :=
ifneq ($(strip $(DEMO_HOST_IP)),)
DOCKER_HOST_MAP_ARGS += --add-host demo.local.deltastream.io:$(DEMO_HOST_IP)
endif
ifneq ($(strip $(API_HOST_IP)),)
DOCKER_HOST_MAP_ARGS += --add-host api.local.deltastream.io:$(API_HOST_IP)
endif

.PHONY: help venv install run clean clean-cache docker-build docker-run docker-run-detached docker-stop

help:
	@printf "Targets:\n"
	@printf "  venv                 Create local virtual environment (.venv)\n"
	@printf "  install              Install Python dependencies\n"
	@printf "  run                  Run Streamlit locally\n"
	@printf "  clean                Remove local build/dependency artifacts\n"
	@printf "  clean-cache          Remove caches without deleting .venv\n"
	@printf "  docker-build         Build Docker image\n"
	@printf "  docker-run           Run Docker container in foreground\n"
	@printf "  docker-run-detached  Run Docker container in background\n"
	@printf "  docker-stop          Stop and remove Docker container\n"
	@printf "\n"
	@printf "Optional: map demo/api hostnames into the container.\n"
	@printf "  make docker-run DEMO_HOST_IP=195.252.249.195\n"
	@printf "Or pass raw Docker flags with DOCKER_EXTRA_ARGS.\n"

venv:
	$(PYTHON) -m venv $(VENV_DIR)

install: venv
	$(VENV_PYTHON) -m pip install --upgrade pip
	$(VENV_PYTHON) -m pip install -r requirements.txt

run:
	API_TOKEN="$(API_TOKEN)" SIGNUP_API_URL="$(SIGNUP_API_URL)" ANTHROPIC_BASE_URL="$(ANTHROPIC_BASE_URL)" DELTASTREAM_MCP_URL="$(DELTASTREAM_MCP_URL)" INSECURE_DEMO_TLS="$(INSECURE_DEMO_TLS)" $(VENV_PYTHON) -m streamlit run app.py --server.port $(PORT)

clean:
	rm -rf .venv
	$(MAKE) clean-cache

clean-cache:
	rm -rf build dist *.egg-info
	rm -rf __pycache__ src/__pycache__
	rm -rf .pytest_cache .mypy_cache .ruff_cache

docker-build:
	docker build -t $(IMAGE_NAME):$(IMAGE_TAG) .

docker-run:
	docker run --rm -it --name $(CONTAINER_NAME) -p $(PORT):8501 -e API_TOKEN="$(API_TOKEN)" -e SIGNUP_API_URL="$(SIGNUP_API_URL)" -e ANTHROPIC_BASE_URL="$(ANTHROPIC_BASE_URL)" -e DELTASTREAM_MCP_URL="$(DELTASTREAM_MCP_URL)" -e INSECURE_DEMO_TLS="$(INSECURE_DEMO_TLS)" $(DOCKER_HOST_MAP_ARGS) $(DOCKER_EXTRA_ARGS) $(IMAGE_NAME):$(IMAGE_TAG)

docker-run-detached:
	docker run -d --rm --name $(CONTAINER_NAME) -p $(PORT):8501 -e API_TOKEN="$(API_TOKEN)" -e SIGNUP_API_URL="$(SIGNUP_API_URL)" -e ANTHROPIC_BASE_URL="$(ANTHROPIC_BASE_URL)" -e DELTASTREAM_MCP_URL="$(DELTASTREAM_MCP_URL)" -e INSECURE_DEMO_TLS="$(INSECURE_DEMO_TLS)" $(DOCKER_HOST_MAP_ARGS) $(DOCKER_EXTRA_ARGS) $(IMAGE_NAME):$(IMAGE_TAG)

docker-stop:
	-docker stop $(CONTAINER_NAME)
