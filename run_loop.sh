#!/bin/bash
cd /home/z/my-project/vimax-agnes
while true; do
    python -u run_keyframes_persistent.py
    echo "Pipeline exited at $(date), restarting in 60s..."
    sleep 60
done