# backends.py
"""
Language/platform backends for code generation.
Each backend handles code generation, compilation, and testing for a specific target.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import textwrap
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from llm_session import LLMSession, Role
from processors import Interface, OutputType, TestPlan


@dataclass
class BuildResult:
    """Result of a build attempt."""
    success: bool
    output_path: Optional[Path] = None
    error_message: str = ""
    stdout: str = ""
    stderr: str = ""


@dataclass
class TestResult:
    """Result of running tests."""
    success: bool
    passed: int = 0
    failed: int = 0
    errors: List[str] = None
    stdout: str = ""
    stderr: str = ""

    def __post_init__(self):
        if self.errors is None:
            self.errors = []


class Backend(ABC):
    """Abstract base class for language/platform backends."""

    def __init__(self, session: LLMSession, build_dir: Path):
        self.session = session
        self.build_dir = build_dir
        self.build_dir.mkdir(parents=True, exist_ok=True)

    @property
    @abstractmethod
    def name(self) -> str:
        """Backend identifier."""
        pass

    @property
    @abstractmethod
    def file_extension(self) -> str:
        """File extension for generated source code."""
        pass

    @abstractmethod
    def generate_code(
        self,
        spec_content: str,
        interface: Interface,
        test_plan: TestPlan,
        previous_error: Optional[str] = None,
    ) -> Tuple[str, str]:
        """
        Generate source code and test code.
        
        Args:
            spec_content: Original gistpp specification
            interface: Generated interface
            test_plan: Generated test plan
            previous_error: Error from previous iteration (for fixing)
            
        Returns:
            Tuple of (source_code, test_code)
        """
        pass

    @abstractmethod
    def build(self, source_path: Path, output_path: Path) -> BuildResult:
        """
        Build/compile the source code.
        
        Args:
            source_path: Path to source code
            output_path: Desired output path
            
        Returns:
            BuildResult with success status and any errors
        """
        pass

    @abstractmethod
    def run_tests(self, test_path: Path, source_path: Path) -> TestResult:
        """
        Run the generated tests.
        
        Args:
            test_path: Path to test code
            source_path: Path to source code being tested
            
        Returns:
            TestResult with pass/fail counts and errors
        """
        pass


class PythonBackend(Backend):
    """
    Python backend for code generation.
    
    - No compilation needed (build is a no-op copy)
    - Uses pytest for testing
    - Generates Python 3.10+ compatible code
    """

    @property
    def name(self) -> str:
        return "Python"

    @property
    def file_extension(self) -> str:
        return ".py"

    def generate_code(
        self,
        spec_content: str,
        interface: Interface,
        test_plan: TestPlan,
        previous_error: Optional[str] = None,
    ) -> Tuple[str, str]:
        """Generate Python source and test code."""

        error_context = ""
        if previous_error:
            error_context = f"""
IMPORTANT: The previous attempt failed with this error:
{previous_error}

Fix this error in your generated code.
"""

        # Generate main source code
        if interface.output_type == OutputType.EXECUTABLE:
            source_prompt = self._get_executable_prompt(
                spec_content, interface, error_context)
        else:
            source_prompt = self._get_library_prompt(spec_content, interface,
                                                     error_context)

        source_code = self.session.chat(source_prompt)
        source_code = self._extract_code_block(source_code)

        # Generate test code
        test_prompt = f"""Generate pytest tests for this Python code.

Source code:
```python
{source_code}
```

Interface:
{interface.to_json()}

Test plan (implement these as actual pytest tests):
{test_plan.to_json()}

Requirements:
1. Use pytest style (def test_xxx functions)
2. Import the source module appropriately
3. Each test case from the plan should become a test function
4. Use assert statements for verification
5. Handle both success and error cases
6. Make tests runnable standalone

Return ONLY the Python test code, no explanations."""

        test_code = self.session.chat(test_prompt)
        test_code = self._extract_code_block(test_code)

        return source_code, test_code

    def _get_executable_prompt(self, spec_content: str, interface: Interface,
                               error_context: str) -> str:
        return f"""Generate Python code for this console application specification.

Specification:
{spec_content}

Interface to implement:
{interface.to_json()}
{error_context}
Requirements:
1. Use argparse for command line argument parsing
2. Include a main() function and if __name__ == "__main__" block
3. Handle all specified arguments, stdin/stdout as per the interface
4. Return appropriate exit codes
5. Include proper error handling
6. Make it a complete, runnable script
7. Use Python 3.10+ features if helpful
8. Include docstrings

Return ONLY the Python code, no explanations."""

    def _get_library_prompt(self, spec_content: str, interface: Interface,
                            error_context: str) -> str:
        return f"""Generate Python code for this library specification.

Specification:
{spec_content}

Interface to implement:
{interface.to_json()}
{error_context}
Requirements:
1. Implement all types, functions, and methods from the interface
2. Use dataclasses or regular classes as appropriate
3. Include type hints
4. Include docstrings
5. Implement operator overloads where specified
6. Make it importable as a module
7. Use Python 3.10+ features if helpful

Return ONLY the Python code, no explanations."""

    def _extract_code_block(self, response: str) -> str:
        """Extract Python code from markdown code blocks if present."""
        lines = response.split('\n')
        in_code_block = False
        code_lines = []

        for line in lines:
            if line.strip().startswith('```python') or line.strip() == '```py':
                in_code_block = True
                continue
            elif line.strip() == '```' and in_code_block:
                in_code_block = False
                continue
            elif in_code_block:
                code_lines.append(line)

        if code_lines:
            return '\n'.join(code_lines)

        # No code block found, assume entire response is code
        # But strip any leading/trailing markdown
        response = response.strip()
        if response.startswith('```'):
            # Remove first line
            response = '\n'.join(response.split('\n')[1:])
        if response.endswith('```'):
            response = response[:-3]

        return response.strip()

    def build(self, source_path: Path, output_path: Path) -> BuildResult:
        """
        Python 'build' - just syntax check and copy.
        """
        try:
            # Syntax check by compiling
            source_code = source_path.read_text(encoding='utf-8')
            compile(source_code, str(source_path), 'exec')

            # Copy to output
            output_path.write_text(source_code, encoding='utf-8')

            # Make executable on Unix
            if sys.platform != 'win32':
                output_path.chmod(0o755)

            return BuildResult(success=True, output_path=output_path)

        except SyntaxError as e:
            return BuildResult(
                success=False,
                error_message=f"Syntax error at line {e.lineno}: {e.msg}",
            )
        except Exception as e:
            return BuildResult(
                success=False,
                error_message=str(e),
            )

    def run_tests(self, test_path: Path, source_path: Path) -> TestResult:
        """Run pytest on the generated tests."""

        # Ensure source is importable by putting it in the same directory
        # or adjusting sys.path
        source_dir = source_path.parent
        test_dir = test_path.parent

        try:
            # Run pytest with verbose output
            result = subprocess.run([
                sys.executable, '-m', 'pytest',
                str(test_path), '-v', '--tb=short'
            ],
                                    capture_output=True,
                                    text=True,
                                    timeout=60,
                                    cwd=str(source_dir),
                                    env={
                                        **dict(subprocess.os.environ),
                                        'PYTHONPATH':
                                        str(source_dir),
                                    })

            stdout = result.stdout
            stderr = result.stderr

            # Parse pytest output
            passed = stdout.count(' PASSED')
            failed = stdout.count(' FAILED')
            errors = []

            if failed > 0 or result.returncode != 0:
                # Extract failure info
                if 'FAILED' in stdout:
                    errors.append(stdout)
                if stderr:
                    errors.append(stderr)

            return TestResult(
                success=(result.returncode == 0),
                passed=passed,
                failed=failed,
                errors=errors,
                stdout=stdout,
                stderr=stderr,
            )

        except subprocess.TimeoutExpired:
            return TestResult(
                success=False,
                errors=["Test execution timed out (60s limit)"],
            )
        except Exception as e:
            return TestResult(
                success=False,
                errors=[f"Failed to run tests: {e}"],
            )


def get_backend(
    name: str,
    session: LLMSession,
    build_dir: Path,
) -> Backend:
    """Factory to get backend by name."""
    backends = {
        "python": PythonBackend,
        "py": PythonBackend,
    }

    backend_class = backends.get(name.lower())
    if not backend_class:
        raise ValueError(
            f"Unknown backend: {name}. Available: {list(backends.keys())}")

    return backend_class(session, build_dir)


def infer_backend_from_output(output_path: Path) -> str:
    """Infer backend from output file extension."""
    ext = output_path.suffix.lower()

    ext_map = {
        '.py': 'python',
        '.pyw': 'python',
        # Future backends:
        # '.exe': 'cpp',
        # '.so': 'cpp',
        # '.dll': 'cpp',
        # '.rs': 'rust',
    }

    backend = ext_map.get(ext)
    if not backend:
        # Default to python for bootstrap
        return 'python'

    return backend
