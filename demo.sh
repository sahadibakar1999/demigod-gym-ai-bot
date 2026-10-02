#!/bin/bash
# Opens the pitch demo at http://localhost:8000
cd "$(dirname "$0")"
[ -d venv ] || python3 -m venv venv
source venv/bin/activate
pip install -q -r requirements.txt
(sleep 2 && open http://localhost:8000) &
uvicorn app:app --port 8000
