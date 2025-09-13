# Local Responses API — skeleton

Minimal FastAPI app with JSON logging and SQLite init.

## Requirements
- Python 3.13
- `pip install -r requirements.txt`

## Run (dev)
```bash
python -m venv .venv
. .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
# or if using Local_Ai entry
uvicorn Local_Ai:app --host 127.0.0.1 --port 8080
```

## Environment
Copy `.env.example` to `.env` and adjust values.

## Endpoints
- `GET /health` -> `{ "status": "ok" }`
- `GET /config` -> returns non-secret runtime configuration
- `POST /responses` -> create response from input_text
- `GET /responses/{response_id}` -> response record with output_text, thread_id, usage
- `GET /threads/{thread_id}/messages?limit=50` -> last messages (chronological)
- `GET /threads/{thread_id}/summary` -> current summary

## Curl checks
```bash
# Health
curl -s http://localhost:8000/health | jq .

# Create response (Linux/macOS bash)
curl -s -X POST http://127.0.0.1:8080/responses \
  -H 'Content-Type: application/json' \
  -d '{"input_text":"Hello!"}' | jq .

# Create response (Windows CMD)
curl -s -X POST http://127.0.0.1:8080/responses -H "Content-Type: application/json" -d "{\"input_text\":\"Hello!\"}"

# Get response by id
curl -s http://127.0.0.1:8080/responses/<response_id> | jq .

# Get thread messages
curl -s "http://127.0.0.1:8080/threads/<thread_id>/messages?limit=50" | jq .

# Get thread summary
curl -s http://127.0.0.1:8080/threads/<thread_id>/summary | jq .
```

## Notes
- On startup, app applies `schema.sql` to SQLite DB at `data/local_api.db` (Local_Ai) or `data/app.db` (skeleton main).
- Logs are JSON to stdout via stdlib logging + json formatter.
