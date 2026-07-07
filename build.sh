#!/usr/bin/env bash
set -euo pipefail
# Build de despliegue en Replit: frontend estático + deps backend
cd frontend && npm ci && npm run build && cd ..
pip install -e "./backend[prod]"
