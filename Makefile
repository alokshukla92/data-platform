.DEFAULT_GOAL := help
SHELL := /bin/bash
COMPOSE := docker compose
KIND_CLUSTER := data-platform

.PHONY: help
help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'

# ---------------------------------------------------------------- local dev
.PHONY: install
install: ## Install python deps + dev tooling (editable)
	pip install -e ".[dev]"

.PHONY: up
up: ## Start full local stack (docker compose)
	$(COMPOSE) up -d --build

.PHONY: down
down: ## Stop local stack
	$(COMPOSE) down

.PHONY: logs
logs: ## Tail app logs
	$(COMPOSE) logs -f gateway ingestion retrieval worker

.PHONY: migrate
migrate: ## Run DB migrations
	$(COMPOSE) run --rm migrate

.PHONY: seed
seed: ## Bootstrap a demo tenant + sample data
	python scripts/seed.py

# ---------------------------------------------------------------- quality
.PHONY: lint
lint: ## Ruff lint
	ruff check .

.PHONY: fmt
fmt: ## Ruff format
	ruff format .

.PHONY: typecheck
typecheck: ## mypy
	mypy libs services workers

.PHONY: test
test: ## Run unit tests with coverage
	pytest -m "not integration" --cov --cov-report=term-missing

.PHONY: test-integration
test-integration: ## Run integration tests (requires stack up)
	pytest -m integration

.PHONY: security
security: ## Static security scan (bandit) + dependency audit
	bandit -r libs services workers -ll
	pip-audit || true

# ---------------------------------------------------------------- kubernetes (kind)
.PHONY: kind-up
kind-up: ## Create local kind cluster + ingress
	kind create cluster --name $(KIND_CLUSTER) --config deploy/kind/kind-config.yaml
	kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/main/deploy/static/provider/kind/deploy.yaml

.PHONY: kind-down
kind-down: ## Delete local kind cluster
	kind delete cluster --name $(KIND_CLUSTER)

.PHONY: kind-load
kind-load: ## Build app image and load into kind
	docker build -t data-platform:dev -f docker/Dockerfile .
	kind load docker-image data-platform:dev --name $(KIND_CLUSTER)

.PHONY: argocd-install
argocd-install: ## Install ArgoCD into the cluster
	kubectl create namespace argocd --dry-run=client -o yaml | kubectl apply -f -
	kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml

.PHONY: helm-install
helm-install: ## Install platform umbrella chart (local values)
	helm upgrade --install data-platform deploy/helm/data-platform \
		-n data-platform --create-namespace \
		-f deploy/helm/data-platform/values-local.yaml

# ---------------------------------------------------------------- perf / chaos
.PHONY: loadtest
loadtest: ## Run k6 load test against gateway
	k6 run tests/load/search_load.js

.PHONY: chaos
chaos: ## Apply chaos experiment (pod kill)
	kubectl apply -f tests/chaos/pod-kill.yaml
