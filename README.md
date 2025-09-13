# Local Responses API

Minimal FastAPI app with JSON logging and SQLite init.

## Requirements
- Python 3.13
- `pip install -r requirements.txt`

## Run (dev)
```bash
python -m venv .venv
. .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
uvicorn Local_Ai:app --host 127.0.0.1 --port 8080
```

## Environment
Copy `.env.example` to `.env` and adjust values.

## Endpoints
- `POST /responses` -> create response from input_text (+ tool calling)
- `GET /responses/{response_id}` -> response record with output_text, thread_id, usage
- `GET /threads/{thread_id}/messages?limit=50` -> last messages (chronological)
- `GET /threads/{thread_id}/summary` -> current summary
- `POST /threads/{thread_id}/summarize` -> force summarization
- `GET /file/{id}` -> serve local file from ./files/{id}

## Tool calling demo (vision)
1) Put a file into `./files`, e.g. `./files/cat.jpg`
2) Prompt so controller calls vision_describe. Examples:

Windows PowerShell:
```powershell
$body = '{
  "input_text": "Опиши картинку: /file/cat.jpg",
  "store": true
}'
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8080/responses -ContentType 'application/json' -Body $body
```

Linux/macOS bash:
```bash
curl -s -X POST http://127.0.0.1:8080/responses \
  -H 'Content-Type: application/json' \
  -d '{"input_text":"Опиши картинку: /file/cat.jpg", "store": true}' | jq .
```

Direct LM Studio call (vision):
```bash
export LM_BASE_URL=http://127.0.0.1:1234/v1
curl -s -X POST "$LM_BASE_URL/chat/completions" \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "qwen2.5-vl-7b-instruct@q8_0",
    "messages": [
      {
        "role": "user",
        "content": [
          {"type": "text", "text": "Describe the image."},
          {"type": "image_url", "image_url": {"url": "http://127.0.0.1:8080/file/cat.jpg"}}
        ]
      }
    ],
    "stream": false
  }' | jq .
```

## Notes
- On startup, app applies `schema.sql` to SQLite DB at the path from env (default `data/local_api.db`).
- Logs are JSON to stdout via stdlib logging + json formatter.
- The vision_describe tool calls LM Studio model qwen2.5-vl-7b-instruct@q8_0 with multimodal messages and returns structured JSON.
