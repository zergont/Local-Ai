# Local Responses API

Minimal FastAPI app with JSON logging, SQLite init, streaming LLM proxy and optional vision tool.

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

### Key env vars
| Purpose | Var | Default |
|---------|-----|---------|
| Chat model | LOCALAPI_LLM_MODEL | qwen/qwen3-14b |
| Vision model | LOCALAPI_VISION_MODEL | qwen2.5-vl-7b-instruct@q8_0 |
| Context messages (max recent) | LOCALAPI_MAX_CONTEXT_MESSAGES | 12 |
| Auto summarization trigger | LOCALAPI_SUMMARIZE_AFTER_MESSAGES | 16 |
| Token window (model) | LOCALAPI_CONTEXT_WINDOW_TOKENS | 32768 |
| Prompt budget ratio | LOCALAPI_CONTEXT_PROMPT_BUDGET_RATIO | 0.6 |
| Hysteresis tokens | LOCALAPI_CONTEXT_HYSTERESIS_TOKENS | 1024 |
| Max upload MB | LOCALAPI_MAX_UPLOAD_MB | 25 |
| Allowed extensions | LOCALAPI_ALLOWED_EXTS | .png,.jpg,.jpeg,.webp,.gif,.pdf,.txt |
| Base public URL (absolute links) | LOCALAPI_APP_BASE_URL | http://127.0.0.1:8080 |

Budget logic: prompt portion = CONTEXT_WINDOW_TOKENS * CONTEXT_PROMPT_BUDGET_RATIO. Если текущая сборка контекста превышает budget + hysteresis → тихая "свёртка" (fold) истории в summary. Если после свёртки всё ещё > budget — уменьшаются последние сообщения (уменьшение K с коэффициентом 0.7).

## Endpoints
- `POST /responses` -> create response from input_text (single streaming call collected server-side)
- `GET /responses/{response_id}` -> response record with output_text, thread_id, usage
- `GET /threads/{thread_id}/messages?limit=50` -> last messages (chronological)
- `GET /threads/{thread_id}/summary` -> current summary
- `POST /threads/{thread_id}/summarize` -> force summarization
- `GET /file/{id}` -> serve local file from ./files/{id}
- `GET /config` -> runtime non-secret config (includes upload + context settings)
- UI: `GET /` (chat), `POST /ui/upload` (file upload)
- WS streaming: `/ws/respond` (deltas: start, delta, end). Final log line: `{"phase":"final","model":"<model>","stream":true,"thread_id":"..."}`

## Files & media
- Upload endpoint: `/ui/upload` checks size, extension whitelist, mime, stores files as `<sha256><suffix>` in `./files`. Duplicate content deduplicated.
- Returned JSON contains absolute URL: `${APP_BASE_URL}/file/<sha256><suffix>`.
- `/file/{sha.ext}` only serves files within the `files` directory (path traversal blocked).

## Streaming model call
Один вызов `/v1/chat/completions` со `stream=true`. SSE чанки проксируются. REST вариант собирает результат.

## Silent history folding (summary)
При переполнении бюджета скрытый запрос:
```
Сожми историю диалога в краткий конспект. Сохрани имена, предпочтения, задачи, факты и ссылки. Будь кратким и точным.
```
Результат сохраняется в `summaries` и добавляется как system message.

## User memory (profiles)
Фраза вида «запомни, что меня зовут Алекс» сохраняет `user.name=Алекс` в таблицу `profiles`. При сборке контекста добавляется system строка: `Факты о пользователе: имя = Алекс.`

## Tool (vision demo)
Инструмент `vision_describe` (multimodal). Для изображения используйте абсолютный URL из аплоада.

## File uploads example
```bash
curl -F "file=@tests/cat.jpg" http://127.0.0.1:8080/ui/upload
# -> {"url":"http://127.0.0.1:8080/file/<sha>.jpg","size":12345}
```

## Notes
- On startup: applies `schema.sql`.
- JSON logs to stdout.
- Vision tool uses LM Studio `qwen2.5-vl-7b-instruct@q8_0`.
