import os
from dotenv import load_dotenv

load_dotenv()


def get_hello_agent():
    """Return a Swarms Agent configured to say Hello World.

    Defaults to Groq Cloud OpenAI-compatible model from env or
    'openai/gpt-oss-20b'.
    """
    try:
        from swarms import Agent
    except Exception as e:  # pragma: no cover
        raise RuntimeError(f"Swarms Agent unavailable: {e}")

    model_name = os.getenv("AGENT_MODEL_NAME", "openai/gpt-oss-20b")
    return Agent(
        agent_name="Hello-Agent",
        agent_description="Minimal agent that says hello",
        system_prompt="You are a minimal agent. Respond with Hello World.",
        model_name=model_name,
        max_loops=1,
        output_type="str",
        dynamic_temperature_enabled=False,
    )