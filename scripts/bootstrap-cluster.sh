#!/usr/bin/env bash
# scripts/bootstrap-cluster.sh
# One-time setup for GKE cluster. Run once after creating a new cluster.
# Safe to re-run — all steps are idempotent.
#
# Usage:
#   chmod +x scripts/bootstrap-cluster.sh
#   ./scripts/bootstrap-cluster.sh

set -euo pipefail

PROJECT=vintravel-chatbot
CLUSTER=vin-pipeline
ZONE=asia-southeast1-a
REGION=asia-southeast1
REGISTRY=asia-southeast1-docker.pkg.dev
REPO=vin-pipeline
GITHUB_REPO=cds0987/Vin-PipeLine
POOL=github-pool
PROVIDER=github-provider
SA_CI=github-actions

echo "==> [1/5] Get cluster credentials"
gcloud container clusters get-credentials "$CLUSTER" \
  --zone "$ZONE" \
  --project "$PROJECT"

echo "==> [2/5] Grant Artifact Registry reader to GKE node service account"
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')
NODE_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
gcloud projects add-iam-policy-binding "$PROJECT" \
  --member="serviceAccount:${NODE_SA}" \
  --role="roles/artifactregistry.reader" \
  --condition=None \
  --quiet

echo "==> [3/5] Set up Workload Identity Federation for GitHub Actions"

# Create pool (skip if exists)
gcloud iam workload-identity-pools create "$POOL" \
  --location=global \
  --project="$PROJECT" \
  --quiet 2>/dev/null || echo "    Pool already exists, skipping"

# Create provider (skip if exists)
gcloud iam workload-identity-pools providers create-oidc "$PROVIDER" \
  --workload-identity-pool="$POOL" \
  --location=global \
  --project="$PROJECT" \
  --issuer-uri="https://token.actions.githubusercontent.com" \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" \
  --quiet 2>/dev/null || echo "    Provider already exists, skipping"

# Bind CI service account
POOL_FULL="projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL}"
gcloud iam service-accounts add-iam-policy-binding \
  "${SA_CI}@${PROJECT}.iam.gserviceaccount.com" \
  --role="roles/iam.workloadIdentityUser" \
  --member="principalSet://iam.googleapis.com/${POOL_FULL}/attribute.repository/${GITHUB_REPO}" \
  --project="$PROJECT" \
  --quiet

echo "==> [4/5] Create Artifact Registry repository (skip if exists)"
gcloud artifacts repositories create "$REPO" \
  --repository-format=docker \
  --location="$REGION" \
  --project="$PROJECT" \
  --quiet 2>/dev/null || echo "    Repository already exists, skipping"

echo "==> [5/5] Apply k8s secret (values from environment or prompt)"

get_val() {
  local key=$1 default=${2:-}
  if [[ -n "${!key:-}" ]]; then
    echo "${!key}"
  else
    read -rp "    $key [${default}]: " val
    echo "${val:-$default}"
  fi
}

DATABASE_URL=$(get_val DATABASE_URL "postgresql://rag:rag@postgres:5432/ragdb")
QDRANT_API_KEY=$(get_val QDRANT_API_KEY "")
AI_API_KEY=$(get_val AI_API_KEY "sk-placeholder")
AWS_ACCESS_KEY_ID=$(get_val AWS_ACCESS_KEY_ID "")
AWS_SECRET_ACCESS_KEY=$(get_val AWS_SECRET_ACCESS_KEY "")
S3_ENDPOINT=$(get_val S3_ENDPOINT "")
S3_BUCKET=$(get_val S3_BUCKET "")

kubectl create secret generic vin-pipeline-secret \
  --from-literal=DATABASE_URL="$DATABASE_URL" \
  --from-literal=QDRANT_API_KEY="$QDRANT_API_KEY" \
  --from-literal=AI_API_KEY="$AI_API_KEY" \
  --from-literal=AWS_ACCESS_KEY_ID="$AWS_ACCESS_KEY_ID" \
  --from-literal=AWS_SECRET_ACCESS_KEY="$AWS_SECRET_ACCESS_KEY" \
  --from-literal=S3_ENDPOINT="$S3_ENDPOINT" \
  --from-literal=S3_BUCKET="$S3_BUCKET" \
  --dry-run=client -o yaml | kubectl apply -f -

echo ""
echo "Bootstrap complete. Next: push to main to trigger CI/CD deploy."
echo ""
echo "GitHub Secrets required in repo settings:"
echo "  DATABASE_URL, QDRANT_API_KEY, AI_API_KEY"
echo "  AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, S3_ENDPOINT, S3_BUCKET"
echo "  QDRANT_API_KEY (also used by qdrant-integration CI job)"
