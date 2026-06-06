#!/usr/bin/env bash
set -euo pipefail

HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
ENV_FILE="$HERMES_HOME/.env"

mkdir -p "$HERMES_HOME"
touch "$ENV_FILE"

upsert_env() {
  local key="$1"
  local value="$2"
  if grep -q "^${key}=" "$ENV_FILE"; then
    perl -0pi -e "s#^${key}=.*#${key}=${value}#m" "$ENV_FILE"
  else
    printf '%s=%s\n' "$key" "$value" >> "$ENV_FILE"
  fi
}

remove_env() {
  local key="$1"
  perl -0pi -e "s#^${key}=.*\\n##m" "$ENV_FILE"
}

upsert_env API_SERVER_ENABLED true
upsert_env API_SERVER_KEY "${HERMES_API_KEY:-change-me-local-dev}"
upsert_env API_SERVER_HOST "${HERMES_API_HOST:-127.0.0.1}"
upsert_env API_SERVER_PORT "${HERMES_API_PORT:-8642}"
upsert_env API_SERVER_MODEL_NAME "${HERMES_API_MODEL:-hermes-agent}"
upsert_env LM_BASE_URL "${LM_STUDIO_BASE_URL:-http://localhost:1234/v1}"
upsert_env LM_API_KEY "${LM_STUDIO_API_KEY:-lmstudio}"
remove_env OPENAI_API_BASE
remove_env OPENAI_BASE_URL
remove_env OPENAI_API_KEY

MODEL_ID="${HERMES_LM_MODEL:-google/gemma-4-31b}"
VISION_MODEL_ID="${HERMES_VISION_MODEL:-$MODEL_ID}"
CONTEXT_LENGTH="${HERMES_CONTEXT_LENGTH:-64000}"
CONFIG_FILE="$HERMES_HOME/config.yaml"
cat > "$CONFIG_FILE" <<EOF
model:
  provider: "lmstudio"
  default: "$MODEL_ID"
  base_url: "${LM_STUDIO_BASE_URL:-http://localhost:1234/v1}"
  api_key: "${LM_STUDIO_API_KEY:-lmstudio}"
  context_length: $CONTEXT_LENGTH

auxiliary:
  vision:
    provider: "main"
    model: "$VISION_MODEL_ID"
    base_url: "${LM_STUDIO_BASE_URL:-http://localhost:1234/v1}"
    api_key: "${LM_STUDIO_API_KEY:-lmstudio}"
    timeout: 180
EOF

cat <<EOF
Hermes local API settings written to:
  $ENV_FILE
  $CONFIG_FILE

Next:
  1. Make sure LM Studio server is running on ${LM_STUDIO_BASE_URL:-http://localhost:1234/v1}
  2. Start Hermes API Server:
     hermes gateway run

Odysseus expects:
  Hermes API: http://127.0.0.1:8642/v1
  API key:    ${HERMES_API_KEY:-change-me-local-dev}
EOF
