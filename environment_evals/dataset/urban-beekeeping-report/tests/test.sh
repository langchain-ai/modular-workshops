#!/bin/bash
# Copied to /tests/test.sh and run from the working directory once the agent stops.
set -u
mkdir -p /logs/verifier
python3 /tests/verify.py || echo '{"reward": 0.0}' > /logs/verifier/reward.json
