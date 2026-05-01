"""Resolve model id for Swarms → LiteLLM (requires provider prefix, e.g. groq/...)."""

from __future__ import annotations

import os


def get_swarms_model_name() -> str:
    """
    LiteLLM maps models as ``provider/model_id``. Bare ``llama-3.3-70b-versatile`` fails
    token lookup; Groq Cloud uses ``groq/llama-3.3-70b-versatile`` with GROQ_API_KEY.
    """
    default = "groq/llama-3.3-70b-versatile"
    raw = (os.getenv("AGENT_MODEL_NAME") or default).strip()
    if not raw:
        return default
    if "/" in raw:
        return raw
    if os.getenv("GROQ_API_KEY"):
        return f"groq/{raw}"
    return raw
