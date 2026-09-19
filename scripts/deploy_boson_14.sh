#!/usr/bin/env bash
# Deploy Boson VoiceOps with HA improvements on InnerOS Intel host (.4)
# Run ON the server (ralphiia / 192.168.1.4), not from the laptop.
set -euo pipefail

REPO_DIR="${VOICEOPS_REPO_DIR:-$HOME/inneros/inneros_core/workspaces/inneros-voiceops-one-day-2026}"
BRANCH="${VOICEOPS_DEPLOY_BRANCH:-hackathon/2026-09-18-boson-insforge}"
SERVICE="${VOICEOPS_SERVICE:-inneros-voiceops-boson.service}"
ENV_FILE="${VOICEOPS_ENV_FILE:-$HOME/.config/inneros/voiceops.env}"
PORT="${VOICEOPS_PORT:-8875}"

echo "==> VoiceOps Boson deploy (.4)"
echo "    repo:    $REPO_DIR"
echo "    branch:  $BRANCH"
echo "    service: $SERVICE"
echo "    port:    $PORT"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "ERROR: missing $ENV_FILE (need HASS_TOKEN + BOSON_API_KEY)" >&2
  exit 1
fi
if ! grep -q '^HASS_TOKEN=.\+' "$ENV_FILE"; then
  echo "ERROR: HASS_TOKEN empty in $ENV_FILE" >&2
  exit 1
fi

cd "$REPO_DIR"
git fetch origin "$BRANCH"
git checkout "$BRANCH"
git pull --ff-only origin "$BRANCH"

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
.venv/bin/pip install -U pip
.venv/bin/pip install -e .

mkdir -p "$HOME/.config/systemd/user"
if [[ -f deploy/inneros-voiceops-boson.service.example ]]; then
  sed "s|%h|$HOME|g" deploy/inneros-voiceops-boson.service.example > "$HOME/.config/systemd/user/$SERVICE"
fi

systemctl --user daemon-reload
systemctl --user restart "$SERVICE"
sleep 2

SHA="$(git rev-parse HEAD)"
echo "==> healthz"
curl -sf "http://127.0.0.1:${PORT}/healthz" | python3 -m json.tool
echo "==> ha/controls (expect truth=LIVE)"
curl -sf "http://127.0.0.1:${PORT}/api/ha/controls?limit=3" | python3 -m json.tool
echo "==> deployed SHA: $SHA"
