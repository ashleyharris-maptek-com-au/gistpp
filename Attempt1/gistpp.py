#!/usr/bin/env python3
# gistpp.py
"""
GistPP Compiler - Bootstrap v1

Compiles .gistpp files into executables or libraries using LLM-powered code generation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from backends import Backend, BuildResult, TestResult, get_backend, infer_backend_from_output
from llm_session import LLMConfig, LLMError
from markdown_db import MarkdownDocument
from openai_session import OpenAIChatSession
from processors import (
    Interface,
    OutputType,
    Processor,
    TestPlan,
    ConsoleApplicationProcessor,
    LibraryProcessor,
    get_processor,
)


@dataclass
class CompileConfig:
    """Configuration for compilation."""
    input_path: Path
    output_path: Path
    backend_name: Optional[str] = None
    max_iterations: int = 5
    allow_interface_changes: bool = False
    allow_test_changes: bool = True  # Allow 'useful' test changes
    verbose: bool = False
    api_key: Optional[str] = None
    model: str = "gpt-4o"


@dataclass
class CompileResult:
    """Result of compilation."""
    success: bool
    output_path: Optional[Path] = None
    interface: Optional[Interface] = None
    test_plan: Optional[TestPlan] = None
    iterations: int = 0
    error_message: str = ""
    warnings: list = None

    def __post_init__(self):
        if self.warnings is None:
            self.warnings = []


def compute_input_hash(input_path: Path) -> str:
    """Compute hash of input file for caching."""
    content = input_path.read_text(encoding='utf-8')
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def load_cached_artifacts(
        input_path: Path) -> tuple[Optional[Interface], Optional[TestPlan]]:
    """Load previously generated interface and test plan if they exist."""
    interface_path = input_path.with_suffix('.interface')
    tests_path = input_path.with_suffix('.tests')

    interface = None
    test_plan = None

    if interface_path.exists():
        try:
            interface = Interface.from_json(
                interface_path.read_text(encoding='utf-8'))
        except Exception:
            pass

    if tests_path.exists():
        try:
            test_plan = TestPlan.from_json(
                tests_path.read_text(encoding='utf-8'))
        except Exception:
            pass

    return interface, test_plan


def save_artifacts(input_path: Path, interface: Interface,
                   test_plan: TestPlan) -> None:
    """Save generated interface and test plan."""
    interface_path = input_path.with_suffix('.interface')
    tests_path = input_path.with_suffix('.tests')

    interface_path.write_text(interface.to_json(), encoding='utf-8')
    tests_path.write_text(test_plan.to_json(), encoding='utf-8')


def detect_output_type_from_spec(doc: MarkdownDocument,
                                 session: OpenAIChatSession) -> OutputType:
    """Use LLM to detect output type from specification."""
    content = doc.ToMarkdown()

    prompt = f"""Analyze this specification and determine what type of output it describes.

Specification:
{content}

Options:
1. Executable - A console application, script, or command-line tool
2. Library - A reusable module, package, or library

Respond with JSON: {{"type": "Executable" or "Library", "reason": "brief explanation"}}"""

    result = session.chat_structured(
        prompt, {
            "type": "object",
            "properties": {
                "type": {
                    "type": "string",
                    "enum": ["Executable", "Library"]
                },
                "reason": {
                    "type": "string"
                }
            },
            "required": ["type", "reason"]
        })

    return OutputType.EXECUTABLE if result[
        "type"] == "Executable" else OutputType.LIBRARY


def compile_gistpp(config: CompileConfig) -> CompileResult:
    """
    Main compilation function.
    
    Steps:
    1. Parse the gistpp file
    2. Check dependencies (TODO for v1 - skip for bootstrap)
    3. Generate/update interface
    4. Generate/update test plan
    5. Decide on backend
    6. Generate code
    7. Build and test (iterate until success or max iterations)
    8. Report results
    """
    warnings = []

    # Step 1: Parse input
    if config.verbose:
        print(f"Parsing {config.input_path}...")

    if not config.input_path.exists():
        return CompileResult(
            success=False,
            error_message=f"Input file not found: {config.input_path}",
        )

    doc = MarkdownDocument.FromFile(config.input_path)
    spec_content = doc.ToMarkdown()

    # Step 2: Check dependencies (skipped for bootstrap - no includes)
    # TODO: Implement dependency resolution

    # Create build directory
    build_dir = config.input_path.parent / '.gistpp_build' / config.input_path.stem
    build_dir.mkdir(parents=True, exist_ok=True)

    # Initialize LLM session
    if config.verbose:
        print("Initializing LLM session...")

    system_prompt = """You are a code generation assistant for the GistPP compiler.
Your job is to generate clean, correct, well-documented code that implements specifications precisely.
Always follow the interface definitions exactly. Generate complete, runnable code."""

    try:
        session = OpenAIChatSession(
            model=config.model,
            api_key=config.api_key,
            system_prompt=system_prompt,
            allowed_read_paths=[config.input_path.parent, build_dir],
            allowed_write_paths=[build_dir, config.output_path.parent],
        )
    except Exception as e:
        return CompileResult(
            success=False,
            error_message=f"Failed to initialize LLM session: {e}",
        )

    # Load existing artifacts
    existing_interface, existing_test_plan = load_cached_artifacts(
        config.input_path)

    # Step 3: Detect output type and generate interface
    if config.verbose:
        print("Detecting output type...")

    try:
        output_type = detect_output_type_from_spec(doc, session)
        if config.verbose:
            print(f"  Detected: {output_type.value}")
    except LLMError as e:
        return CompileResult(
            success=False,
            error_message=f"Failed to detect output type: {e}",
        )

    # Get appropriate processor
    processor = get_processor(output_type, session)

    if config.verbose:
        print("Generating interface...")

    try:
        interface = processor.generate_interface(doc, existing_interface)

        # Check if interface changed
        if existing_interface and existing_interface.to_json(
        ) != interface.to_json():
            if not config.allow_interface_changes:
                warnings.append("Interface changed from previous build")

        if config.verbose:
            print(f"  Interface: {len(interface.schema)} items")
    except LLMError as e:
        return CompileResult(
            success=False,
            error_message=f"Failed to generate interface: {e}",
        )

    # Step 4: Generate test plan
    if config.verbose:
        print("Generating test plan...")

    try:
        test_plan = processor.generate_test_plan(doc, interface,
                                                 existing_test_plan)

        if config.verbose:
            print(f"  Tests: {len(test_plan.tests)} cases")
    except LLMError as e:
        return CompileResult(
            success=False,
            error_message=f"Failed to generate test plan: {e}",
        )

    # Save artifacts
    save_artifacts(config.input_path, interface, test_plan)

    # Step 5: Select backend
    backend_name = config.backend_name or infer_backend_from_output(
        config.output_path)
    if config.verbose:
        print(f"Using backend: {backend_name}")

    try:
        backend = get_backend(backend_name, session, build_dir)
    except ValueError as e:
        return CompileResult(
            success=False,
            error_message=str(e),
        )

    # Step 6-7: Generate code, build, test, iterate
    if config.verbose:
        print("Starting code generation and testing loop...")

    previous_error = None

    for iteration in range(1, config.max_iterations + 1):
        if config.verbose:
            print(f"\n=== Iteration {iteration}/{config.max_iterations} ===")

        # Generate code
        if config.verbose:
            print("Generating code...")

        try:
            source_code, test_code = backend.generate_code(
                spec_content,
                interface,
                test_plan,
                previous_error,
            )
        except LLMError as e:
            return CompileResult(
                success=False,
                iterations=iteration,
                interface=interface,
                test_plan=test_plan,
                error_message=f"Code generation failed: {e}",
                warnings=warnings,
            )

        # Write source files
        source_path = build_dir / f"main{backend.file_extension}"
        test_path = build_dir / f"test_main{backend.file_extension}"

        source_path.write_text(source_code, encoding='utf-8')
        test_path.write_text(test_code, encoding='utf-8')

        if config.verbose:
            print(f"  Source: {len(source_code)} chars")
            print(f"  Tests: {len(test_code)} chars")

        # Build
        if config.verbose:
            print("Building...")

        build_result = backend.build(source_path, config.output_path)

        if not build_result.success:
            if config.verbose:
                print(f"  Build failed: {build_result.error_message}")
            previous_error = f"Build error: {build_result.error_message}"
            continue

        if config.verbose:
            print("  Build successful")

        # Run tests
        if config.verbose:
            print("Running tests...")

        test_result = backend.run_tests(test_path, source_path)

        if config.verbose:
            print(
                f"  Passed: {test_result.passed}, Failed: {test_result.failed}"
            )

        if test_result.success:
            if config.verbose:
                print("\n=== SUCCESS ===")

            return CompileResult(
                success=True,
                output_path=config.output_path,
                interface=interface,
                test_plan=test_plan,
                iterations=iteration,
                warnings=warnings,
            )

        # Tests failed - prepare for next iteration
        error_details = "\n".join(
            test_result.errors) if test_result.errors else test_result.stdout
        previous_error = f"Test failures:\n{error_details}"

        if config.verbose:
            print(f"  Test errors: {error_details[:500]}...")

    # Max iterations reached
    return CompileResult(
        success=False,
        output_path=config.output_path,
        interface=interface,
        test_plan=test_plan,
        iterations=config.max_iterations,
        error_message=
        f"Failed to pass all tests after {config.max_iterations} iterations. Last error: {previous_error}",
        warnings=warnings,
    )


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description=
        'GistPP Compiler - Compile .gistpp files to executables or libraries',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  gistpp hello.gistpp -o hello.py
  gistpp math.gistpp -o math.py --backend python
  gistpp app.gistpp -o app.py --max-iterations 10 --verbose
""",
    )

    parser.add_argument('input', type=Path, help='Input .gistpp file')
    parser.add_argument('-o',
                        '--output',
                        type=Path,
                        required=True,
                        help='Output file path')
    parser.add_argument(
        '-b',
        '--backend',
        type=str,
        help='Backend to use (default: inferred from output extension)')
    parser.add_argument('-m',
                        '--model',
                        type=str,
                        default='gpt-4o',
                        help='LLM model to use (default: gpt-4o)')
    parser.add_argument('--max-iterations',
                        type=int,
                        default=5,
                        help='Max build/test iterations (default: 5)')
    parser.add_argument('--allow-interface-changes',
                        action='store_true',
                        help='Allow interface to change from previous builds')
    parser.add_argument(
        '--api-key',
        type=str,
        help='OpenAI API key (default: from OPENAI_API_KEY env)')
    parser.add_argument('-v',
                        '--verbose',
                        action='store_true',
                        help='Verbose output')

    args = parser.parse_args()

    config = CompileConfig(
        input_path=args.input.resolve(),
        output_path=args.output.resolve(),
        backend_name=args.backend,
        max_iterations=args.max_iterations,
        allow_interface_changes=args.allow_interface_changes,
        verbose=args.verbose,
        api_key=args.api_key,
        model=args.model,
    )

    result = compile_gistpp(config)

    # Report results
    if result.success:
        print(f"✓ Successfully compiled {args.input} -> {result.output_path}")
        print(f"  Iterations: {result.iterations}")
        if result.warnings:
            for w in result.warnings:
                print(f"  ⚠ Warning: {w}")
        sys.exit(0)
    else:
        print(f"✗ Failed to compile {args.input}")
        print(f"  Error: {result.error_message}")
        print(f"  Iterations: {result.iterations}")
        if result.warnings:
            for w in result.warnings:
                print(f"  ⚠ Warning: {w}")
        sys.exit(1)


if __name__ == '__main__':
    main()
