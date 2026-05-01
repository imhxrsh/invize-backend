from dotenv import load_dotenv

load_dotenv()

from agents.swarms_model_name import get_swarms_model_name


def get_hello_agent():
    """Return a Swarms Agent configured to say Hello World.

    Model from env via get_swarms_model_name() (default groq/llama-3.3-70b-versatile).
    """
    try:
        from swarms import Agent
    except Exception as e:  # pragma: no cover
        raise RuntimeError(f"Swarms Agent unavailable: {e}")

    model_name = get_swarms_model_name()
    return Agent(
        agent_name="Hello-Agent",
        agent_description="Minimal agent that says hello",
        system_prompt=(
            "You are a smoke-test agent. Reply with exactly the two words: Hello World "
            "(no punctuation, no extra words, no markdown)."
        ),
        model_name=model_name,
        max_loops=1,
        output_type="str",
        dynamic_temperature_enabled=False,
    )