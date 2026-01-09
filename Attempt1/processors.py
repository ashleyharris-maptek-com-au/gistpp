# processors.py
"""
Type-specific processors for gistpp.
Manages interface refinement and test generation.
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from llm_session import LLMSession, Role
from markdown_db import MarkdownDocument, NodeType


class OutputType(Enum):
    LIBRARY = "Library"
    EXECUTABLE = "Executable"
    # NYI types
    UI_APPLICATION = "UIApplication"
    WEB_FRONTEND = "WebFrontEnd"
    EXPERIENCE = "Experience"
    BACKGROUND_TASK = "BackgroundTask"
    CLOUD_SERVICE = "CloudService"


@dataclass
class TestCase:
    """A single test case."""
    name: str
    description: str
    pseudocode: str
    is_contract: bool = False  # Contract tests can't change without user approval


@dataclass
class Interface:
    """Generated interface for the output."""
    output_type: OutputType
    description: str
    schema: Dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(
            {
                "output_type": self.output_type.value,
                "description": self.description,
                "schema": self.schema,
            },
            indent=2)

    @classmethod
    def from_json(cls, data: str) -> "Interface":
        obj = json.loads(data)
        return cls(
            output_type=OutputType(obj["output_type"]),
            description=obj["description"],
            schema=obj.get("schema", {}),
        )


@dataclass
class TestPlan:
    """Collection of test cases."""
    tests: List[TestCase] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps([{
            "name": t.name,
            "description": t.description,
            "pseudocode": t.pseudocode,
            "is_contract": t.is_contract,
        } for t in self.tests],
                          indent=2)

    @classmethod
    def from_json(cls, data: str) -> "TestPlan":
        obj = json.loads(data)
        return cls(tests=[
            TestCase(
                name=t["name"],
                description=t["description"],
                pseudocode=t["pseudocode"],
                is_contract=t.get("is_contract", False),
            ) for t in obj
        ])


class Processor(ABC):
    """Base class for type-specific processors."""

    def __init__(self, session: LLMSession):
        self.session = session

    @abstractmethod
    def detect_output_type(self, doc: MarkdownDocument) -> OutputType:
        """Determine what type of output we're building."""
        pass

    @abstractmethod
    def generate_interface(self,
                           doc: MarkdownDocument,
                           existing: Optional[Interface] = None) -> Interface:
        """Generate or update the interface based on the gistpp document."""
        pass

    @abstractmethod
    def generate_test_plan(self,
                           doc: MarkdownDocument,
                           interface: Interface,
                           existing: Optional[TestPlan] = None) -> TestPlan:
        """Generate or update the test plan."""
        pass


class ConsoleApplicationProcessor(Processor):
    """
    Processor for console applications (executables).
    
    Handles:
    - Command line argument parsing interface
    - stdin/stdout/stderr interface
    - Exit codes
    - Integration tests
    """

    INTERFACE_SCHEMA = {
        "type": "object",
        "properties": {
            "output_type": {
                "type": "string",
                "enum": ["Executable"]
            },
            "description": {
                "type": "string"
            },
            "schema": {
                "type": "object",
                "properties": {
                    "positional_args": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {
                                    "type": "string"
                                },
                                "type": {
                                    "type": "string"
                                },
                                "description": {
                                    "type": "string"
                                },
                                "optional": {
                                    "type": "boolean"
                                },
                            }
                        }
                    },
                    "flags": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {
                                    "type": "string"
                                },
                                "short": {
                                    "type": "string"
                                },
                                "description": {
                                    "type": "string"
                                },
                                "takes_value": {
                                    "type": "boolean"
                                },
                            }
                        }
                    },
                    "stdin": {
                        "type": "object"
                    },
                    "stdout": {
                        "type": "object"
                    },
                    "stderr": {
                        "type": "object"
                    },
                    "exit_codes": {
                        "type": "object",
                        "additionalProperties": {
                            "type": "string"
                        }
                    },
                }
            }
        }
    }

    TEST_SCHEMA = {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string"
                },
                "description": {
                    "type": "string"
                },
                "pseudocode": {
                    "type": "string"
                },
                "is_contract": {
                    "type": "boolean"
                },
            },
            "required": ["name", "description", "pseudocode"]
        }
    }

    def _extract_content(self, doc: MarkdownDocument) -> str:
        """Extract the main content from the document for LLM processing."""
        return doc.ToMarkdown()

    def detect_output_type(self, doc: MarkdownDocument) -> OutputType:
        """
        Determine output type. For ConsoleApplicationProcessor, we verify it's an executable.
        """
        content = self._extract_content(doc)

        prompt = f"""Analyze this gistpp specification and determine if it describes:
1. An executable/console application
2. A library
3. Something else (UI, web, service, etc.)

Specification:
{content}

Respond with JSON: {{"type": "Executable" or "Library" or "Other", "reason": "brief explanation"}}"""

        result = self.session.chat_structured(
            prompt, {
                "type": "object",
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": ["Executable", "Library", "Other"]
                    },
                    "reason": {
                        "type": "string"
                    }
                },
                "required": ["type", "reason"]
            })

        type_map = {
            "Executable": OutputType.EXECUTABLE,
            "Library": OutputType.LIBRARY,
            "Other": OutputType.EXECUTABLE,  # Default fallback
        }
        return type_map.get(result["type"], OutputType.EXECUTABLE)

    def generate_interface(self,
                           doc: MarkdownDocument,
                           existing: Optional[Interface] = None) -> Interface:
        """Generate interface for a console application."""
        content = self._extract_content(doc)

        existing_context = ""
        if existing:
            existing_context = f"""
There is an existing interface that should be updated if needed:
{existing.to_json()}

Only make changes if the specification requires them. Preserve existing behavior unless explicitly changed.
"""

        prompt = f"""Analyze this gistpp specification and generate an interface definition for a console application.

Specification:
{content}
{existing_context}
Generate a JSON interface with:
- positional_args: List of positional command line arguments
- flags: Optional flags/switches  
- stdin: Description of stdin input if used
- stdout: Description of stdout output
- stderr: Description of stderr output if used
- exit_codes: Map of exit codes to meanings

Be precise and complete. Infer reasonable defaults for anything not specified."""

        result = self.session.chat_structured(prompt, self.INTERFACE_SCHEMA)

        return Interface(
            output_type=OutputType.EXECUTABLE,
            description=result.get("description", ""),
            schema=result.get("schema", {}),
        )

    def generate_test_plan(self,
                           doc: MarkdownDocument,
                           interface: Interface,
                           existing: Optional[TestPlan] = None) -> TestPlan:
        """Generate test plan for console application."""
        content = self._extract_content(doc)

        existing_context = ""
        contract_tests = []
        if existing:
            contract_tests = [t for t in existing.tests if t.is_contract]
            existing_context = f"""
Existing tests (contract tests MUST be preserved exactly):
{existing.to_json()}
"""

        prompt = f"""Generate integration tests for this console application.

Specification:
{content}

Interface:
{interface.to_json()}
{existing_context}
Generate test cases that:
1. Cover all specified behavior from the spec
2. Test edge cases and error handling
3. Verify correct exit codes
4. Test both valid and invalid inputs

Each test should have:
- name: Short descriptive name
- description: What is being tested
- pseudocode: High-level test steps (will be converted to actual test code later)
- is_contract: true if this tests core specified behavior that should never change

Return as JSON array."""

        result = self.session.chat_structured(prompt, self.TEST_SCHEMA)

        tests = [
            TestCase(
                name=t["name"],
                description=t["description"],
                pseudocode=t["pseudocode"],
                is_contract=t.get("is_contract", False),
            ) for t in result
        ]

        # Ensure contract tests from existing are preserved
        existing_contract_names = {t.name for t in contract_tests}
        tests = contract_tests + [
            t for t in tests if t.name not in existing_contract_names
        ]

        return TestPlan(tests=tests)


class LibraryProcessor(Processor):
    """
    Processor for libraries.
    
    Handles:
    - Type definitions (structs, classes, enums)
    - Function signatures
    - Constants
    - Unit tests
    """

    INTERFACE_SCHEMA = {
        "type": "object",
        "properties": {
            "output_type": {
                "type": "string",
                "enum": ["Library"]
            },
            "description": {
                "type": "string"
            },
            "schema": {
                "type": "object",
                "properties": {
                    "types": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "type": {
                                    "type": "string",
                                    "enum": ["Struct", "Class", "Enum"]
                                },
                                "name": {
                                    "type": "string"
                                },
                                "fields": {
                                    "type": "array"
                                },
                                "methods": {
                                    "type": "array"
                                },
                            }
                        }
                    },
                    "functions": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {
                                    "type": "string"
                                },
                                "args": {
                                    "type": "array"
                                },
                                "returns": {
                                    "type": "string"
                                },
                                "description": {
                                    "type": "string"
                                },
                            }
                        }
                    },
                    "constants": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {
                                    "type": "string"
                                },
                                "type": {
                                    "type": "string"
                                },
                                "value": {},
                            }
                        }
                    },
                    "operators": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "type": {
                                    "type": "string"
                                },
                                "name": {
                                    "type": "string"
                                },
                                "args": {
                                    "type": "array"
                                },
                                "returns": {
                                    "type": "string"
                                },
                            }
                        }
                    },
                }
            }
        }
    }

    def _extract_content(self, doc: MarkdownDocument) -> str:
        return doc.ToMarkdown()

    def detect_output_type(self, doc: MarkdownDocument) -> OutputType:
        return OutputType.LIBRARY

    def generate_interface(self,
                           doc: MarkdownDocument,
                           existing: Optional[Interface] = None) -> Interface:
        """Generate interface for a library."""
        content = self._extract_content(doc)

        existing_context = ""
        if existing:
            existing_context = f"\nExisting interface to update:\n{existing.to_json()}\n"

        prompt = f"""Analyze this gistpp specification and generate an interface definition for a library.

Specification:
{content}
{existing_context}
Generate a JSON interface with:
- types: Structs, classes, enums with their fields and methods
- functions: Standalone functions with signatures
- constants: Named constants
- operators: Operator overloads if applicable

Be complete and precise."""

        result = self.session.chat_structured(prompt, self.INTERFACE_SCHEMA)

        return Interface(
            output_type=OutputType.LIBRARY,
            description=result.get("description", ""),
            schema=result.get("schema", {}),
        )

    def generate_test_plan(self,
                           doc: MarkdownDocument,
                           interface: Interface,
                           existing: Optional[TestPlan] = None) -> TestPlan:
        """Generate unit test plan for library."""
        content = self._extract_content(doc)

        existing_context = ""
        contract_tests = []
        if existing:
            contract_tests = [t for t in existing.tests if t.is_contract]
            existing_context = f"\nExisting tests:\n{existing.to_json()}\n"

        prompt = f"""Generate unit tests for this library.

Specification:
{content}

Interface:
{interface.to_json()}
{existing_context}
Generate test cases covering:
1. All public functions and methods
2. Edge cases (empty inputs, boundaries, etc.)
3. Error conditions
4. Any behavior specified in the spec

Return as JSON array with name, description, pseudocode, is_contract fields."""

        result = self.session.chat_structured(
            prompt, ConsoleApplicationProcessor.TEST_SCHEMA)

        tests = [
            TestCase(
                name=t["name"],
                description=t["description"],
                pseudocode=t["pseudocode"],
                is_contract=t.get("is_contract", False),
            ) for t in result
        ]

        existing_contract_names = {t.name for t in contract_tests}
        tests = contract_tests + [
            t for t in tests if t.name not in existing_contract_names
        ]

        return TestPlan(tests=tests)


def get_processor(output_type: OutputType, session: LLMSession) -> Processor:
    """Factory to get appropriate processor for output type."""
    processors = {
        OutputType.EXECUTABLE: ConsoleApplicationProcessor,
        OutputType.LIBRARY: LibraryProcessor,
    }

    processor_class = processors.get(output_type)
    if not processor_class:
        raise ValueError(f"No processor available for {output_type.value}")

    return processor_class(session)
