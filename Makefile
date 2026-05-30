# Makefile — stable interface between CI/CD and codebase.
#
# CI calls exactly 4 targets: test, docker-test, build, deploy.
# Everything else is codebase-internal.
#
# Usage:
#   make test
#   make docker-test
#   make build   IMAGE=... SHA=...
#   make deploy  SHA=...   (requires GKE credentials)

.PHONY: test docker-test lint build push deploy migrate

# ── Registry (override from CI env or command-line) ───────────────────────────

REGISTRY   ?= asia-southeast1-docker.pkg.dev/vintravel-chatbot/vin-pipeline
IMAGE      ?= $(REGISTRY)/api
SHA        ?= $(shell git rev-parse --short HEAD)

# ── Test ──────────────────────────────────────────────────────────────────────

test:
	pytest -q

docker-test:
	docker compose run --rm test

lint:
	ruff check . --select E,F,I && mypy app/ --ignore-missing-imports

# ── Build & push ──────────────────────────────────────────────────────────────

build:
	docker build -f docker/Dockerfile.api \
	  -t $(IMAGE):$(SHA) \
	  -t $(IMAGE):latest \
	  .

push: build
	docker push $(IMAGE):$(SHA)
	docker push $(IMAGE):latest

# ── Deploy ────────────────────────────────────────────────────────────────────

# Pin image SHA into kustomize overlay, then apply everything at once.
# CI calls: make deploy SHA=${{ github.sha }}
deploy:
	cd k8s/overlays/production && \
	  kustomize edit set image api=$(IMAGE):$(SHA)
	kubectl apply -k k8s/overlays/production/
	kubectl rollout status deployment/vin-pipeline-api --timeout=600s

# Restart without new image (config-only change)
restart:
	kubectl rollout restart deployment/vin-pipeline-api
	kubectl rollout status deployment/vin-pipeline-api --timeout=600s

# ── Secret (run once per environment setup) ───────────────────────────────────

apply-secret:
	kubectl create secret generic vin-pipeline-secret \
	  --from-literal=DATABASE_URL=$(DATABASE_URL) \
	  --from-literal=QDRANT_API_KEY=$(QDRANT_API_KEY) \
	  --from-literal=AI_API_KEY=$(AI_API_KEY) \
	  --from-literal=AWS_ACCESS_KEY_ID=$(AWS_ACCESS_KEY_ID) \
	  --from-literal=AWS_SECRET_ACCESS_KEY=$(AWS_SECRET_ACCESS_KEY) \
	  --from-literal=S3_ENDPOINT=$(S3_ENDPOINT) \
	  --from-literal=S3_BUCKET=$(S3_BUCKET) \
	  --dry-run=client -o yaml | kubectl apply -f -
