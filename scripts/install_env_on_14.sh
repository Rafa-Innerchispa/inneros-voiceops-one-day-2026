#!/usr/bin/env bash
# One-shot: install voiceops.env on .4 from repo .env (run ON ralphi-ia-ver-10)
set -euo pipefail
REPO="${1:-$HOME/inneros/inneros_core/workspaces/inneros-voiceops-one-day-2026}"
ENV_DST="$HOME/.config/inneros/voiceops.env"
mkdir -p "$(dirname "$ENV_DST")"
if [[ -f "$REPO/.env" ]]; then
  cp "$REPO/.env" "$ENV_DST"
  chmod 600 "$ENV_DST"
  echo "Installed $ENV_DST from $REPO/.env"
elif [[ -f "$REPO/deploy/voiceops.env.example" ]]; then
  echo "ERROR: $REPO/.env missing — copy laptop .env to server first:" >&2
  echo "  scp .env rlopez@192.168.1.4:$REPO/.env" >&2
  exit 1
fi
systemctl --user restart inneros-voiceops-boson.service
sleep 2
curl -sf "http://127.0.0.1:8875/api/ha/controls?limit=2" | python3 -m json.tool
