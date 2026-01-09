from .openai_session import OpenAIChatSession

system_prompt = """
You are a senior software engineer, helping to plan software engineering tasks at a high level.
"""


def LlmFactory():
    exceptions = []
    try:
        session = OpenAIChatSession(
            model="gpt-5.2-pro-2025-12-11",
            system_prompt=system_prompt,
        )
        return session
    except e:
        exceptions.append(e)

    raise Exception("Failed to create LLM session\n\n" +
                    "\n".join(str(e) for e in exceptions))
