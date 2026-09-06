#!/bin/sh
set -e
# Seed a demo watchlist on first boot so `docker compose up` shows the product
# rather than an empty screen. Idempotent: re-running only refreshes prices.
if [ "${SEED_DEMO:-1}" = "1" ]; then
  python -m scripts.seed_demo || echo "demo seed skipped"
fi
exec python -m worker.main
