#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
REF_TARGET="$ROOT/reference-target"
RESULTS_DIR="$ROOT/test/pipeline_results"
mkdir -p "$RESULTS_DIR"

print_header() {
  echo ""
  echo "============================================================"
  echo " $1"
  echo "============================================================"
}

run_cmd() {
  echo "> $*"
  "$@"
}

print_header "Pipeline simulation - preflight"
run_cmd docker run --rm -v "$REF_TARGET/terraform/aws:/workspace" -w /workspace hashicorp/terraform:0.12.31 fmt -check -recursive -diff || true
run_cmd docker run --rm -v "$REF_TARGET/terraform/aws:/workspace" -w /workspace hashicorp/terraform:0.12.31 init -backend=false > "$RESULTS_DIR/terraform_init.log" 2>&1
run_cmd docker run --rm -v "$REF_TARGET/terraform/aws:/workspace" -w /workspace hashicorp/terraform:0.12.31 validate > "$RESULTS_DIR/terraform_validate.log" 2>&1 || true

print_header "Pipeline simulation - secrets detection"
run_cmd docker run --rm -v "$ROOT:/repo" -w /repo ghcr.io/gitleaks/gitleaks:v8.21.0 detect --source /repo --verbose --no-git > "$RESULTS_DIR/gitleaks.log" 2>&1 || true

print_header "Pipeline simulation - IaC scanning"
run_cmd docker run --rm -v "$ROOT:/iac" bridgecrew/checkov:3.2.0 -d /iac --output json > "$RESULTS_DIR/checkov_output.json" 2>&1 || true
run_cmd docker run --rm -v "$ROOT:/iac" aquasec/trivy:0.55.2 config --severity CRITICAL,HIGH --exit-code 1 --format sarif --output "$RESULTS_DIR/trivy-iac-report.sarif" /iac > "$RESULTS_DIR/trivy_iac.log" 2>&1 || true
run_cmd docker run --rm -v "$ROOT:/iac" aquasec/tfsec:latest /iac --format json > "$RESULTS_DIR/tfsec_output.json" 2>&1 || true

print_header "Pipeline simulation - dependency / SBOM"
run_cmd docker run --rm -v "$ROOT:/iac" aquasec/trivy:0.55.2 fs --scanners vuln --severity CRITICAL,HIGH --exit-code 1 --format sarif --output "$RESULTS_DIR/trivy-sca-report.sarif" /iac > "$RESULTS_DIR/trivy_sca.log" 2>&1 || true
run_cmd docker run --rm -v "$ROOT:/iac" anchore/syft:latest dir:/iac --output cyclonedx-json="${RESULTS_DIR}/sbom-${CI_COMMIT_SHORT_SHA:-local}.cdx.json"

print_header "Pipeline simulation - container scan"
if [ -f "$ROOT/Dockerfile" ] || [ -f "$ROOT/Containerfile" ]; then
  IMAGE_TAG="local-demo:latest"
  run_cmd docker build -t "$IMAGE_TAG" "$ROOT"
  run_cmd docker run --rm aquasec/trivy:0.55.2 image --severity CRITICAL,HIGH --exit-code 1 --format sarif --output "$RESULTS_DIR/container-scan-report.sarif" "$IMAGE_TAG" > "$RESULTS_DIR/trivy_container.log" 2>&1 || true
else
  echo "Skipping container scan: no Dockerfile or Containerfile found"
fi

print_header "Pipeline simulation complete"
echo "Results saved in $RESULTS_DIR"
