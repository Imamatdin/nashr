#!/bin/bash
set -euo pipefail
cd /root/nashr
docker exec nashr-bot pkill -f proof_build1_critic 2>/dev/null || true
sleep 1
docker cp /root/nashr/scripts/proof_build1_critic.py nashr-bot:/app/scripts/proof_build1_critic.py
rm -f /root/nashr/debug/build1_gate.log
rm -f /root/nashr/debug/build1_enlightenment_deck.json
rm -f /root/nashr/debug/build1_sco2_deck.json
nohup docker exec nashr-bot bash -lc 'cd /app && PYTHONUNBUFFERED=1 python scripts/proof_build1_critic.py' \
  > /root/nashr/debug/build1_gate.log 2>&1 &
echo "gate pid=$!"
