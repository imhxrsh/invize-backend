"""Shared helpers for LLM outputs that should be JSON but may be messy or markdown-fenced."""

from __future__ import annotations

import json
from typing import Any, Dict, Iterator, List


def strip_json_fence(s: str) -> str:
    t = (s or "").strip()
    if not t.startswith("```"):
        return t
    lines = t.split("\n")
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def iter_json_dict_candidates(s: str) -> Iterator[Dict[str, Any]]:
    """
    Scan text for top-level JSON objects and yield each parsed dict.
    Handles trailing garbage and multiple objects (common with LLMs).
    """
    if not (s or "").strip():
        return
    decoder = json.JSONDecoder()
    i = 0
    n = len(s)
    while i < n:
        while i < n and s[i].isspace():
            i += 1
        if i >= n:
            break
        if s[i] != "{":
            i += 1
            continue
        try:
            obj, end = decoder.raw_decode(s, i)
            i = end
            if isinstance(obj, dict):
                yield obj
        except json.JSONDecodeError:
            i += 1


def json_loads_object_candidates(text: str) -> List[Dict[str, Any]]:
    """Return unique dicts we can extract from text (fenced, whole string, scanned)."""
    out: List[Dict[str, Any]] = []
    seen: set = set()
    chunks: List[str] = []
    t = (text or "").strip()
    if t:
        chunks.append(strip_json_fence(t))
        chunks.append(t)
    for chunk in chunks:
        if not chunk:
            continue
        try:
            obj = json.loads(chunk)
            if isinstance(obj, dict):
                key = json.dumps(obj, sort_keys=True, default=str)
                if key not in seen:
                    seen.add(key)
                    out.append(obj)
        except json.JSONDecodeError:
            pass
    for obj in iter_json_dict_candidates(t):
        key = json.dumps(obj, sort_keys=True, default=str)
        if key not in seen:
            seen.add(key)
            out.append(obj)
    return out
