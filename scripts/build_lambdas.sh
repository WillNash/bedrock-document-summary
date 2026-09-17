#!/usr/bin/env bash
# build_lambdas.sh — Build the Lambda layer zip (jinja2, jsonschema).
# Run this before every `terraform apply`.
#
# Bundling rules:
#   schemas/  →  extractor zip  AND  validator zip   (Terraform archive_file handles this)
#   templates/ →  renderer zip                        (Terraform archive_file handles this)
#   layer.zip  →  shared Python deps (jinja2, jsonschema) for validator + renderer
#
# The Terraform archive_file data sources in lambda.tf bundle schemas and templates
# directly, so this script only needs to build the Lambda layer.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LAYER_SRC="$REPO_ROOT/lambda/lambda_layer_packages"
LAYER_ZIP="$REPO_ROOT/infra/lambda_packages/layer.zip"
REQUIREMENTS="$REPO_ROOT/lambda/requirements.txt"

echo "==> Building Lambda dependency layer..."

# Clean previous build
rm -rf "$LAYER_SRC"
mkdir -p "$LAYER_SRC/python"

# Install dependencies into the layer structure
# Lambda layers expect: python.zip with /python/<package> at root
pip install \
  --quiet \
  --target "$LAYER_SRC/python" \
  -r "$REQUIREMENTS"

# Remove unnecessary files to reduce zip size
find "$LAYER_SRC" -type d -name "*.dist-info" -exec rm -rf {} + 2>/dev/null || true
find "$LAYER_SRC" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find "$LAYER_SRC" -name "*.pyc" -delete 2>/dev/null || true

# Create the zip
cd "$LAYER_SRC"
zip -rq "$LAYER_ZIP" python/
cd "$REPO_ROOT"

echo "==> Layer zip created at: $LAYER_ZIP"
echo ""
echo "==> Done. You can now run: terraform -chdir=infra init && terraform -chdir=infra apply"
echo ""
echo "NOTE: Terraform archive_file data sources handle bundling schemas/ and templates/"
echo "      into the extractor, validator, and renderer Lambda zips automatically."
echo "      You do not need to copy those directories manually."
