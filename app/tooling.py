"""Tool interface, registry, and small utilities.

- Tool Protocol (name, parameters_schema, async invoke)
- VisionDescribeTool: calls LM Studio multimodal model; strict args validation
- list_tools(), tools_openai_format(), maybe_call_one_tool()
- now_ts(), new_id()
"""
from __future__ import annotations

import asyncio
import json
import random
import re
import time
import uuid
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

import httpx

from .config import get_settings
from .logging_utils import log_error, log_info


__all__ = [
    "Tool",
    "list_tools",
    "tools_openai_format",
    "maybe_call_one_tool",
    "now_ts",
    "new_id",
]


def now_ts() -> float:
    return time.time()


def new_id() -> str:
    return str(uuid.uuid4())


@runtime_checkable
class Tool(Protocol):
    name: str
    parameters_schema: Dict[str, Any]

    async def invoke(self, **kwargs: Any) -> Dict[str, Any]:  # pragma: no cover - async interface
        ...


def _validate_args(schema: Dict[str, Any], args: Dict[str, Any]) -> Dict[str, Any]:
    required = schema.get("required", [])
    props = schema.get("properties", {})
    validated: Dict[str, Any] = {}
    for key in required:
        if key not in args:
            raise ValueError(f"Missing required parameter: {key}")
    for key, val in args.items():
        if key not in props:
            raise ValueError(f"Unknown parameter: {key}")
        spec = props[key]
        t = spec.get("type")
        if t == "string":
            if not isinstance(val, str):
                raise ValueError(f"Parameter {key} must be string")
            if "enum" in spec and val not in spec["enum"]:
                raise ValueError(f"Parameter {key} must be one of {spec['enum']}")
        validated[key] = val
    for key, spec in props.items():
        if key not in validated and "default" in spec:
            validated[key] = spec["default"]
    return validated


class VisionDescribeTool:
    name = "vision_describe"
    parameters_schema: Dict[str, Any] = {
        "type": "object",
        "properties": {
            "image_url": {"type": "string", "description": "Publicly reachable image URL"},
            "task": {
                "type": "string",
                "enum": ["general", "ocr", "layout"],
                "default": "general",
                "description": "Description mode: general, OCR text extraction, or layout analysis",
            },
        },
        "required": ["image_url"],
        "additionalProperties": False,
    }

    async def invoke(self, **kwargs: Any) -> Dict[str, Any]:
        s = get_settings()
        base = s.llm_base_url.rstrip("/")
        model = s.vision_model
        args = _validate_args(self.parameters_schema, dict(kwargs))
        image_url = args["image_url"].strip()
        task = args.get("task", "general")

        instruction = (
            "You are a vision assistant. Analyze the provided image and reply ONLY with compact JSON having keys: "
            "summary (string), objects (array of strings), detected_text (array of strings), tags (array of strings)."
        )
        if task == "ocr":
            instruction += " Focus on extracting visible text into detected_text and short summary."
        elif task == "layout":
            instruction += " Focus on layout/objects list; detected_text only if clearly visible."

        messages: List[Dict[str, Any]] = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": instruction},
                    {"type": "image_url", "image_url": {"url": image_url}},
                ],
            }
        ]

        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": 0,
            "max_tokens": 512,
            "stream": False,
        }

        # network call with retries and jitter
        max_retries = 3
        last_err: Optional[Exception] = None
        for attempt in range(1, max_retries + 1):
            t0 = time.perf_counter()
            try:
                async with httpx.AsyncClient(timeout=60.0) as client:
                    resp = await client.post(f"{base}/chat/completions", json=payload)
                    resp.raise_for_status()
                    data = resp.json()
                dt_ms = int((time.perf_counter() - t0) * 1000)
                log_info("tool_call_http", tool=self.name, model=model, latency_ms=dt_ms)
                break
            except (httpx.TimeoutException, httpx.RequestError, httpx.HTTPStatusError) as e:
                last_err = e
                dt_ms = int((time.perf_counter() - t0) * 1000)
                log_error("tool_call_http_error", tool=self.name, model=model, latency_ms=dt_ms, error=str(e))
                if attempt >= max_retries:
                    raise
                base_wait = 0.25 * (2 ** (attempt - 1))
                jitter = random.uniform(0, 0.15)
                await asyncio.sleep(base_wait + jitter)
        assert last_err is None

        text = (
            data.get("choices", [{}])[0]
            .get("message", {})
            .get("content")
        ) or ""

        # Try parse strict JSON, else extract the largest JSON object
        parsed: Optional[Dict[str, Any]] = None
        try:
            parsed = json.loads(text)
        except Exception:
            match = re.search(r"\{[\s\S]*\}", text)
            if match:
                try:
                    parsed = json.loads(match.group(0))
                except Exception:
                    parsed = None
        if not isinstance(parsed, dict):
            parsed = {"summary": text.strip(), "objects": [], "detected_text": [], "tags": []}

        def as_list(v: Any) -> List[str]:
            if v is None:
                return []
            if isinstance(v, list):
                return [str(x) for x in v]
            return [str(v)]

        result = {
            "summary": str(parsed.get("summary", "")).strip(),
            "objects": as_list(parsed.get("objects", [])),
            "detected_text": as_list(parsed.get("detected_text", [])),
            "tags": as_list(parsed.get("tags", [])),
        }
        return result


def list_tools() -> List[Tool]:
    return [VisionDescribeTool()]


def tools_openai_format() -> List[Dict[str, Any]]:
    tools: List[Dict[str, Any]] = []
    for t in list_tools():
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": f"Function tool: {t.name}",
                    "parameters": t.parameters_schema,
                },
            }
        )
    return tools


async def maybe_call_one_tool(messages: List[Dict[str, Any]], probe_raw: Dict[str, Any]) -> tuple[List[Dict[str, Any]], bool]:
    """If probe_raw contains a tool call, execute it and append tool message to messages.

    Returns possibly modified messages and a flag whether a tool was called.
    """
    try:
        tool_calls = probe_raw.get("choices", [{}])[0].get("message", {}).get("tool_calls")
    except Exception:
        tool_calls = None
    if not tool_calls:
        return messages, False
    call = tool_calls[0]
    fn = call.get("function", {})
    name = str(fn.get("name", ""))
    arguments = fn.get("arguments")
    if isinstance(arguments, str):
        try:
            args_obj = json.loads(arguments)
        except Exception:
            args_obj = {}
    elif isinstance(arguments, dict):
        args_obj = arguments
    else:
        args_obj = {}
    tool_map = {t.name: t for t in list_tools()}
    tool = tool_map.get(name)
    if not tool:
        return messages, False
    try:
        result = await tool.invoke(**args_obj)
    except Exception as e:  # noqa: BLE001
        result = {"error": str(e)}
    messages = messages + [{"role": "tool", "name": name, "content": json.dumps(result, ensure_ascii=False)}]
    return messages, True
