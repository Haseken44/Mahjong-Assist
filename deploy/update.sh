#!/usr/bin/env bash
# サーバー上で最新版に更新して再起動する: bash deploy/update.sh
set -euo pipefail
cd "$(dirname "$0")/.."
git pull --ff-only
.venv/bin/pip install -q -r requirements.txt
sudo systemctl restart mahjong-assist
sleep 2
curl -fsS http://127.0.0.1:8030/healthz && echo
