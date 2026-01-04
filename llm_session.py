# llm_session.py
"""
Abstract base class for LLM sessions.
Provides conversation memory, tool calling, and structured output.
"""
from __future__ import annotations

import json
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union


class Role(Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass
class Message:
    role: Role
    content: str
    tool_calls: Optional[List[Dict[str, Any]]] = None
    tool_call_id: Optional[str] = None
    name: Optional[str] = None  # For tool responses


@dataclass
class ToolDefinition:
    """Definition of a tool the LLM can call."""
    name: str
    description: str
    parameters: Dict[str, Any]  # JSON Schema format
    handler: Callable[..., str]


@dataclass
class LLMConfig:
    """Configuration for LLM session."""
    max_tokens: int = 4096
    temperature: float = 0.2
    max_retries: int = 3
    retry_base_delay: float = 1.0  # Exponential backoff base
    max_tool_calls: int = 50
    max_bytes_read: int = 100_000
    max_bytes_written: int = 100_000
    timeout_seconds: float = 120.0


@dataclass
class SessionState:
    """Compacted state for token saving."""
    summary: str
    key_decisions: List[str] = field(default_factory=list)
    files_modified: List[str] = field(default_factory=list)
    current_task: str = ""


class LLMError(Exception):
    """Base exception for LLM errors."""
    pass


class RateLimitError(LLMError):
    """Rate limit hit - should retry with backoff."""
    pass


class SafetyFilterError(LLMError):
    """Content blocked by safety filters - abort."""
    pass


class NetworkError(LLMError):
    """Network error - may retry."""
    pass


class OutOfCreditsError(LLMError):
    """Out of API credits - abort."""
    pass


class BadOutputError(LLMError):
    """LLM produced unparseable output - may retry."""
    pass


class LLMSession(ABC):
    """
    Abstract base class for LLM API wrappers.
    
    Provides:
    - Conversation memory with compaction
    - System prompt management
    - Tool calling with file read/write restrictions
    - Exponential backoff on rate limits
    - Graceful abort on fatal errors
    """

    def __init__(
        self,
        config: Optional[LLMConfig] = None,
        system_prompt: str = "",
        allowed_read_paths: Optional[List[Path]] = None,
        allowed_write_paths: Optional[List[Path]] = None,
    ):
        self.config = config or LLMConfig()
        self.messages: List[Message] = []
        self.system_prompt = system_prompt
        self.tools: Dict[str, ToolDefinition] = {}
        self.tool_call_count = 0
        self.bytes_read = 0
        self.bytes_written = 0

        # File access restrictions
        self.allowed_read_paths = allowed_read_paths or []
        self.allowed_write_paths = allowed_write_paths or []

        # Register built-in file tools
        self._register_file_tools()

    def _register_file_tools(self) -> None:
        """Register built-in file read/write tools."""
        self.register_tool(
            ToolDefinition(
                name="read_file",
                description=
                "Read contents of a file. Only allowed for permitted paths.",
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Path to file to read"
                        }
                    },
                    "required": ["path"]
                },
                handler=self._tool_read_file))

        self.register_tool(
            ToolDefinition(
                name="write_file",
                description=
                "Write contents to a file. Only allowed for permitted paths.",
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Path to file to write"
                        },
                        "content": {
                            "type": "string",
                            "description": "Content to write"
                        }
                    },
                    "required": ["path", "content"]
                },
                handler=self._tool_write_file))

    def _is_path_allowed(self, path: Path, allowed_paths: List[Path]) -> bool:
        """Check if path is within any allowed path."""
        path = path.resolve()
        for allowed in allowed_paths:
            allowed = allowed.resolve()
            try:
                path.relative_to(allowed)
                return True
            except ValueError:
                continue
        return False

    def _tool_read_file(self, path: str) -> str:
        """Built-in tool: read a file."""
        p = Path(path)
        if not self._is_path_allowed(
                p, self.allowed_read_paths + self.allowed_write_paths):
            return f"Error: Access denied to path: {path}"

        if not p.exists():
            return f"Error: File not found: {path}"

        try:
            content = p.read_text(encoding="utf-8")
            if self.bytes_read + len(content) > self.config.max_bytes_read:
                return f"Error: Would exceed max bytes read limit ({self.config.max_bytes_read})"
            self.bytes_read += len(content)
            return content
        except Exception as e:
            return f"Error reading file: {e}"

    def _tool_write_file(self, path: str, content: str) -> str:
        """Built-in tool: write a file."""
        p = Path(path)
        if not self._is_path_allowed(p, self.allowed_write_paths):
            return f"Error: Write access denied to path: {path}"

        if self.bytes_written + len(content) > self.config.max_bytes_written:
            return f"Error: Would exceed max bytes written limit ({self.config.max_bytes_written})"

        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            self.bytes_written += len(content)
            return f"Successfully wrote {len(content)} bytes to {path}"
        except Exception as e:
            return f"Error writing file: {e}"

    def register_tool(self, tool: ToolDefinition) -> None:
        """Register a tool the LLM can call."""
        self.tools[tool.name] = tool

    def add_message(self, role: Role, content: str, **kwargs) -> None:
        """Add a message to conversation history."""
        self.messages.append(Message(role=role, content=content, **kwargs))

    def compact_history(self) -> SessionState:
        """
        Compact conversation history to save tokens.
        Returns a summary state and clears old messages.
        """
        # Ask LLM to summarize the conversation
        summary_prompt = """Summarize the conversation so far in a concise way that preserves:
1. Key decisions made
2. Files created or modified
3. Current task status
4. Any errors encountered and how they were resolved

Be brief but complete."""

        # For now, simple compaction - keep last few messages
        state = SessionState(summary="Conversation compacted",
                             key_decisions=[],
                             files_modified=[],
                             current_task="")

        # Keep only recent messages
        if len(self.messages) > 10:
            # Create summary message
            old_messages = self.messages[:-5]
            summary_content = f"[Previous conversation summary: {len(old_messages)} messages compacted]"
            self.messages = [
                Message(role=Role.SYSTEM, content=summary_content)
            ] + self.messages[-5:]

        return state

    def _execute_tool_call(self, name: str, arguments: Dict[str, Any]) -> str:
        """Execute a tool call and return the result."""
        if self.tool_call_count >= self.config.max_tool_calls:
            return f"Error: Maximum tool call limit ({self.config.max_tool_calls}) reached"

        if name not in self.tools:
            return f"Error: Unknown tool: {name}"

        self.tool_call_count += 1
        tool = self.tools[name]

        try:
            return tool.handler(**arguments)
        except Exception as e:
            return f"Error executing tool {name}: {e}"

    def _retry_with_backoff(self, func: Callable, *args, **kwargs) -> Any:
        """Execute function with exponential backoff on rate limits."""
        last_error = None

        for attempt in range(self.config.max_retries):
            try:
                return func(*args, **kwargs)
            except RateLimitError as e:
                last_error = e
                delay = self.config.retry_base_delay * (2**attempt)
                print(
                    f"Rate limited, waiting {delay}s before retry {attempt + 1}/{self.config.max_retries}"
                )
                time.sleep(delay)
            except NetworkError as e:
                last_error = e
                delay = self.config.retry_base_delay * (2**attempt)
                print(
                    f"Network error, waiting {delay}s before retry {attempt + 1}/{self.config.max_retries}"
                )
                time.sleep(delay)
            except BadOutputError as e:
                last_error = e
                print(
                    f"Bad output, retrying {attempt + 1}/{self.config.max_retries}"
                )
                continue
            except (SafetyFilterError, OutOfCreditsError):
                # Fatal errors - don't retry
                raise

        raise last_error or LLMError("Max retries exceeded")

    @abstractmethod
    def _call_api(self, messages: List[Message]) -> Message:
        """
        Make the actual API call. Must be implemented by subclasses.
        
        Should raise appropriate LLMError subclasses:
        - RateLimitError for 429 responses
        - SafetyFilterError for content policy violations
        - NetworkError for connection issues
        - OutOfCreditsError for billing issues
        - BadOutputError for unparseable responses
        """
        pass

    @abstractmethod
    def _call_api_structured(self, messages: List[Message],
                             schema: Dict[str, Any]) -> Dict[str, Any]:
        """
        Make API call expecting structured JSON output.
        
        Args:
            messages: Conversation messages
            schema: JSON schema for expected output
            
        Returns:
            Parsed JSON response matching schema
        """
        pass

    def chat(self, user_message: str) -> str:
        """
        Send a message and get a response, handling tool calls automatically.
        """
        self.add_message(Role.USER, user_message)

        while True:
            # Prepare messages for API
            api_messages = []
            if self.system_prompt:
                api_messages.append(
                    Message(role=Role.SYSTEM, content=self.system_prompt))
            api_messages.extend(self.messages)

            # Call API with retry
            response = self._retry_with_backoff(self._call_api, api_messages)
            self.messages.append(response)

            # Handle tool calls
            if response.tool_calls:
                for tool_call in response.tool_calls:
                    name = tool_call["function"]["name"]
                    args = json.loads(tool_call["function"]["arguments"])
                    result = self._execute_tool_call(name, args)

                    self.add_message(Role.TOOL,
                                     result,
                                     tool_call_id=tool_call["id"],
                                     name=name)
                # Continue loop to get next response after tool results
                continue

            # No tool calls - return the response
            return response.content

    def chat_structured(self, user_message: str,
                        schema: Dict[str, Any]) -> Dict[str, Any]:
        """
        Send a message and get a structured JSON response.
        """
        self.add_message(Role.USER, user_message)

        api_messages = []
        if self.system_prompt:
            api_messages.append(
                Message(role=Role.SYSTEM, content=self.system_prompt))
        api_messages.extend(self.messages)

        result = self._retry_with_backoff(self._call_api_structured,
                                          api_messages, schema)

        # Add response to history
        self.add_message(Role.ASSISTANT, json.dumps(result))

        return result

    def reset(self) -> None:
        """Clear conversation history and counters."""
        self.messages.clear()
        self.tool_call_count = 0
        self.bytes_read = 0
        self.bytes_written = 0
