#!/bin/bash
cd /home/irene/dota_poly_bot_final
PYTHONUNBUFFERED=1 nohup python3 main.py > data/bot_g3.log 2>&1 &
echo $! > data/bot_g3.pid
echo "Started PID=$(cat data/bot_g3.pid)"
