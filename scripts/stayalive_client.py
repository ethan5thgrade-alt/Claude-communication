"""Tiny test client — imports connect.py (which auto-starts the WS loop) then
just sleeps so the instance stays registered. Env vars must be set BEFORE
running: INSTANCE_ID, INSTANCE_NAME, INSTANCE_EMAIL, INSTANCE_ROLE, BROKER_URL.

Usage:
    INSTANCE_ID=cc-test-1 INSTANCE_NAME=test-one INSTANCE_EMAIL=a@x.com \\
        python3 scripts/stayalive_client.py
"""
import os
import sys
import time

# Make sure we can import connect.py from the repo root regardless of CWD.
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)

import connect  # noqa: F401  (importing triggers the connection loop)

print(f"[stayalive] id={connect.INSTANCE_ID} name={connect.NAME} "
      f"email={connect.EMAIL} role={connect.ROLE}", flush=True)

try:
    while True:
        time.sleep(60)
except KeyboardInterrupt:
    pass
