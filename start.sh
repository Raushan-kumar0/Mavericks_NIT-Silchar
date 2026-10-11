#!/usr/bin/env bash
# Starts ML service (8000), Spring Boot backend (8080) and React dashboard (5173).
set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT/ml-service"
pip install -q -r requirements.txt
[ -f models/glucotwin_models.joblib ] || python train.py
uvicorn app:app --port 8000 &
ML=$!
cd "$ROOT/backend" && mvn -q spring-boot:run &
BE=$!
cd "$ROOT/frontend" && npm install --silent && npm run dev &
FE=$!
trap "kill $ML $BE $FE 2>/dev/null" EXIT
echo "GlucoTwin starting... open http://localhost:5173 (backend may take ~20 s)"
wait
