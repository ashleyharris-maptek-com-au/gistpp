# openai_session.py
"""
OpenAI implementation of LLMSession.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from llm_session import (
    BadOutputError,
    LLMConfig,
    LLMSession,
    Message,
    NetworkError,
    OutOfCreditsError,
    RateLimitError,
    Role,
    SafetyFilterError,
)

try:
    import openai
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False
    OpenAI = None


class OpenAIChatSession(LLMSession):
    """
    OpenAI API implementation of LLMSession.
    
    Supports GPT-4, GPT-4-turbo, GPT-3.5-turbo, etc.
    """

    def __init__(
        self,
        model: str = "gpt-4o",
        api_key: Optional[str] = None,
        config: Optional[LLMConfig] = None,
        system_prompt: str = "",
        allowed_read_paths: Optional[List[Path]] = None,
        allowed_write_paths: Optional[List[Path]] = None,
    ):
        super().__init__(
            config=config,
            system_prompt=system_prompt,
            allowed_read_paths=allowed_read_paths,
            allowed_write_paths=allowed_write_paths,
        )

        if not OPENAI_AVAILABLE:
            raise ImportError(
                "openai package not installed. Run: pip install openai")

        self.model = model
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")

        if not self.api_key:
            raise ValueError(
                "OpenAI API key required. Set OPENAI_API_KEY env var or pass api_key parameter."
            )

        self.client = OpenAI(api_key=self.api_key)

    def _message_to_openai(self, msg: Message) -> Dict[str, Any]:
        """Convert internal Message to OpenAI format."""
        result: Dict[str, Any] = {
            "role": msg.role.value,
            "content": msg.content or "",
        }

        if msg.tool_calls:
            result["tool_calls"] = msg.tool_calls

        if msg.role == Role.TOOL:
            result["tool_call_id"] = msg.tool_call_id
            if msg.name:
                result["name"] = msg.name

        return result

    def _get_tools_spec(self) -> List[Dict[str, Any]]:
        """Get OpenAI tools specification."""
        if not self.tools:
            return []

        return [{
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
            }
        } for tool in self.tools.values()]

    def _call_api(self, messages: List[Message]) -> Message:
        """Make the actual OpenAI API call."""
        openai_messages = [self._message_to_openai(m) for m in messages]
        tools = self._get_tools_spec()

        try:
            kwargs = {
                "model": self.model,
                "messages": openai_messages,
                "max_tokens": self.config.max_tokens,
                "temperature": self.config.temperature,
            }

            if tools:
                kwargs["tools"] = tools
                kwargs["tool_choice"] = "auto"

            response = self.client.chat.completions.create(**kwargs)

            choice = response.choices[0]
            message = choice.message

            # Extract tool calls if present
            tool_calls = None
            if message.tool_calls:
                tool_calls = [{
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    }
                } for tc in message.tool_calls]

            return Message(
                role=Role.ASSISTANT,
                content=message.content or "",
                tool_calls=tool_calls,
            )

        except openai.RateLimitError as e:
            raise RateLimitError(str(e)) from e
        except openai.AuthenticationError as e:
            raise OutOfCreditsError(
                f"Authentication failed (possibly out of credits): {e}") from e
        except openai.APIConnectionError as e:
            raise NetworkError(str(e)) from e
        except openai.BadRequestError as e:
            # Could be content policy violation
            error_msg = str(e).lower()
            if "content" in error_msg and ("policy" in error_msg
                                           or "filter" in error_msg):
                raise SafetyFilterError(str(e)) from e
            raise BadOutputError(str(e)) from e
        except Exception as e:
            raise NetworkError(f"Unexpected error: {e}") from e

    def _call_api_structured(self, messages: List[Message],
                             schema: Dict[str, Any]) -> Dict[str, Any]:
        """Make API call expecting structured JSON output."""
        # Add schema instruction to the last user message
        schema_instruction = f"\n\nRespond with valid JSON matching this schema:\n```json\n{json.dumps(schema, indent=2)}\n```"

        # Create modified messages with schema instruction
        modified_messages = messages.copy()
        if modified_messages and modified_messages[-1].role == Role.USER:
            last_msg = modified_messages[-1]
            modified_messages[-1] = Message(
                role=last_msg.role,
                content=last_msg.content + schema_instruction,
            )

        openai_messages = [
            self._message_to_openai(m) for m in modified_messages
        ]

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=openai_messages,
                max_tokens=self.config.max_tokens,
                temperature=self.config.temperature,
                response_format={"type": "json_object"},
            )

            content = response.choices[0].message.content

            try:
                return json.loads(content)
            except json.JSONDecodeError as e:
                raise BadOutputError(
                    f"Failed to parse JSON response: {e}\nContent: {content[:500]}"
                ) from e

        except openai.RateLimitError as e:
            raise RateLimitError(str(e)) from e
        except openai.AuthenticationError as e:
            raise OutOfCreditsError(f"Authentication failed: {e}") from e
        except openai.APIConnectionError as e:
            raise NetworkError(str(e)) from e
        except openai.BadRequestError as e:
            error_msg = str(e).lower()
            if "content" in error_msg and ("policy" in error_msg
                                           or "filter" in error_msg):
                raise SafetyFilterError(str(e)) from e
            raise BadOutputError(str(e)) from e


def create_session(
    model: str = "gpt-4o",
    api_key: Optional[str] = None,
    system_prompt: str = "",
    project_path: Optional[Path] = None,
    build_path: Optional[Path] = None,
    output_path: Optional[Path] = None,
) -> OpenAIChatSession:
    """
    Factory function to create a configured OpenAI session.
    
    Args:
        model: OpenAI model to use
        api_key: API key (or use OPENAI_API_KEY env var)
        system_prompt: System prompt for the session
        project_path: Project directory (read access)
        build_path: Build directory (read/write access)
        output_path: Output file path (read/write access)
    """
    read_paths = []
    write_paths = []

    if project_path:
        read_paths.append(Path(project_path))
    if build_path:
        read_paths.append(Path(build_path))
        write_paths.append(Path(build_path))
    if output_path:
        write_paths.append(Path(output_path).parent)

    return OpenAIChatSession(
        model=model,
        api_key=api_key,
        system_prompt=system_prompt,
        allowed_read_paths=read_paths,
        allowed_write_paths=write_paths,
    )
