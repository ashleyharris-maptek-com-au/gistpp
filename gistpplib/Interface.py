from .markdown_db import MarkdownDocument
from .Parser import GistPPParser
from .llm_session import LLMSession
from .Constants import *


def generate_interface(parsed: GistPPParser, raw: str, existing: str,
                       llm: LLMSession) -> dict:
    if parsed.target_type == "Executable":
        prompt = f"""

-------

{raw}

--------

Generate an interface (and serialize it as JSON) with:
- positional_args: List of positional command line arguments
- flags: Optional flags/switches  
- stdin: Description of stdin input if used
- stdout: Description of stdout output
- stderr: Description of stderr output if used
- exit_codes: Map of exit codes to meanings

Be precise and complete. Infer reasonable defaults for anything not specified."""

        if existing == "":
            prompt = "Analyze this specification and generate an interface definition for a console application." + prompt
        else:
            prompt = "Analyze this specification and improve this interface defintion:\n\n" \
                 + existing + "\n\n" + prompt + \
                    "\nIf the interface doesn't need to be changed, respond with the same interface."

        result = llm.chat_structured(prompt, EXECUTABLE_INTERFACE_SCHEMA)

        return result

    if parsed.target_type == "Library":

        prompt = f"""

-------

{raw}

-------

Generate an interface (and serialize it as JSON) with:
- types: Structs, classes, enums with their fields and methods
- functions: Standalone functions with signatures
- constants: Named constants
- operators: Operator overloads if applicable

Be complete and precise."""

        if existing == "":
            prompt = "Analyze this specification and generate an interface definition for a library." + prompt
        else:
            prompt = "Analyze this specification and improve this interface defintion:\n\n" \
                 + existing + "\n\n" + prompt + \
                    "\nIf the interface doesn't need to be changed, respond with the same interface."

        result = llm.chat_structured(prompt, LIBRARY_INTERFACE_SCHEMA)

        return result

    assert False
