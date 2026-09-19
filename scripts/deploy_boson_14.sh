#!/usr/bin/env bash
# Deploy Boson VoiceOps with HA improvements on InnerOS Intel host (.4)
#
# IMPORTANT: Run ON the Linux server (ralphiia / 192.168.1.4), NOT on Windows PowerShell.
# From Windows, first:  ssh rlopez@192.168.1.4   (or ssh rlopez@100.94.99.12 via Tailscale)
#
set -euo pipefail

BRANCH="${VOICEOPS_DEPLOY_BRANCH:-hackathon/2026-09-18-boson-insforge}"
SERVICE="${VOICEOPS_SERVICE:-inneros-voiceops-boson.service}"
ENV_FILE="${VOICEOPS_ENV_FILE:-$HOME/.config/inneros/voiceops.env}"
PORT="${VOICEOPS_PORT:-8875}"
REPO_URL="${VOICEOPS_REPO_URL:-https://github.com/Rafa-Innerchispa/inneros-voiceops-one-day-2026.git}"

detect_repo_dir() {
  if [[ -n "${VOICEOPS_REPO_DIR:-}" && -d "$VOICEOPS_REPO_DIR" ]]; then
    echo "$VOICEOPS_REPO_DIR"
    return
  fi
  local candidates=(
    "$HOME/inneros/inneros_core/workspaces/inneros-voiceops-one-day-2026"
    "$HOME/inneros-voiceops-one-day-2026"
    "/opt/inneros/inneros-voiceops-one-day-2026"
  )
  for dir in "${candidates[@]}"; do
    if [[ -d "$dir/.git" ]]; then
      echo "$dir"
      return
    fi
  done
  if systemctl --user show "$SERVICE" -p WorkingDirectory --value 2>/dev/null | grep -q .; then
    systemctl --user show "$SERVICE" -p WorkingDirectory --value
    return
  fi
  echo ""
}

bootstrap_repo() {
  local target="${1:-$HOME/inneros/inneros_core/workspaces/inneros-voiceops-one-day-2026}"
  echo "==> Cloning repo (first-time bootstrap)"
  mkdir -p "$(dirname "$target")"
  git clone --branch "$BRANCH" "$REPO_URL" "$target"
  echo "$target"
}

REPO_DIR="$(detect_repo_dir)"
if [[ -z "$REPO_DIR" || ! -d "$REPO_DIR/.git" ]]; then
  REPO_DIR="$(bootstrap_repo "${REPO_DIR:-$HOME/inneros/inneros_core/workspaces/inneros-voiceops-one-day-2026}")"
fi

echo "==> VoiceOps Boson deploy (.4)"
echo "    host:    $(hostname)"
echo "    repo:    $REPO_DIR"
echo "    branch:  $BRANCH"
echo "    service: $SERVICE"
echo "    port:    $PORT"

mkdir -p "$(dirname "$ENV_FILE")"
if [[ -f "$REPO_DIR/.env" && ! -f "$ENV_FILE" ]]; then
  cp "$REPO_DIR/.env" "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  echo "==> Installed $ENV_FILE from repo .env"
fi
if ! grep -q '^HASS_TOKEN=.\+' "$ENV_FILE" 2>/dev/null; then
  BOOTSTRAP_URL="${VOICEOPS_ENV_BOOTSTRAP_URL:-http://100.83.210.41:8766/voiceops.env.bootstrap}"
  echo "==> Fetching env bootstrap from laptop ($BOOTSTRAP_URL)"
  if curl -sf "$BOOTSTRAP_URL" -o "$ENV_FILE"; then
    chmod 600 "$ENV_FILE"
  fi
fi
if [[ ! -f "$ENV_FILE" ]]; then
  echo "ERROR: missing $ENV_FILE" >&2
  echo "       Create it with HASS_URL, HASS_TOKEN, BOSON_API_KEY (see deploy/voiceops.env.example)" >&2
  exit 1
fi
if ! grep -q '^HASS_TOKEN=.\+' "$ENV_FILE"; then
  echo "ERROR: HASS_TOKEN empty in $ENV_FILE" >&2
  exit 1
fi
# Also mirror into repo .env for runtime_env.py first candidate path
if [[ -f "$ENV_FILE" && ! -f "$REPO_DIR/.env" ]]; then
  cp "$ENV_FILE" "$REPO_DIR/.env"
  chmod 600 "$REPO_DIR/.env"
fi

cd "$REPO_DIR"
git fetch origin "$BRANCH"
git checkout "$BRANCH"
git pull --ff-only origin "$BRANCH"

if [[ ! -f scripts/deploy_boson_14.sh ]]; then
  echo "ERROR: scripts/deploy_boson_14.sh missing after git pull — check branch $BRANCH" >&2
  exit 1
fi

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
.venv/bin/pip install -U pip
.venv/bin/pip install -e .

mkdir -p "$HOME/.config/systemd/user"
if [[ -f deploy/inneros-voiceops-boson.service.example ]]; then
  sed "s|%h|$HOME|g" deploy/inneros-voiceops-boson.service.example > "$HOME/.config/systemd/user/$SERVICE"
  # Ensure WorkingDirectory matches actual repo path on this host.
  sed -i "s|WorkingDirectory=.*|WorkingDirectory=$REPO_DIR|" "$HOME/.config/systemd/user/$SERVICE"
  sed -i "s|ExecStart=.*python|ExecStart=$REPO_DIR/.venv/bin/python|" "$HOME/.config/systemd/user/$SERVICE"
fi

systemctl --user daemon-reload
systemctl --user enable "$SERVICE" 2>/dev/null || true
systemctl --user restart "$SERVICE"
sleep 2

SHA="$(git rev-parse HEAD)"
echo "==> healthz"
curl -sf "http://127.0.0.1:${PORT}/healthz" | python3 -m json.tool
echo "==> ha/controls (expect truth=LIVE)"
curl -sf "http://127.0.0.1:${PORT}/api/ha/controls?limit=3" | python3 -m json.tool
echo "==> deployed SHA: $SHA"
