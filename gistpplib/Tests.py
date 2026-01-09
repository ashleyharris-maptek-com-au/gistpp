from .llm_session import LLMSession
from .Parser import GistPPParser
from .Constants import TEST_SCHEMA
import json
import hashlib

test_types = ["contract", "unit", "integration", "edge"]


def _package_tests(tests: list, hashCode: str) -> str:
  return json.dumps(tests)


def generate_tests(parsed: GistPPParser, raw: str, existing: str, test_change: tuple,
                   interface: str, llm: LLMSession) -> dict:

  hashCode = hashlib.sha256(raw.encode()).hexdigest()

  if existing:
    existing_tests = json.loads(existing)
    if existing_tests["hashCode"] == hashCode:
      return existing_tests
    existing_tests = existing_tests["tests"]

  prompt = f"""

Here is the users specification we need to test:
-----------

{raw}

-----------

Here is the interface we need to test:
-----------

{interface}

-----------

"""

  if existing:

    test_change, contract_change = test_change
    if contract_change:
      prompt = "Can we redo this test plan? (any can be changed, including contract tests)\n\n" + prompt
    elif test_change:
      prompt = "Can we improve this test plan? (contract tests can't be changed)\n\n" + prompt
    else:
      prompt = "Can we extend this test plan by adding new ones?\n\n" + prompt
    prompt += \
        "\n\nHere is the existing test plan:\n-----------\n\n" + \
            existing + \
                "\n\n-----------\n\n"
  else:
    prompt = "Can we generate a comprehensive test plan for this specification and interface?\n\n" + prompt

  prompt += """       
Each test should be:
- Written in a high-level psuedocode stepping through the testing process.
- Classified:
    - contract: Tests that are either requested by the user as part of the spec, 
            or otherwise fundamental behavior that should be fixed within a major version.
    - unit: Tests a single function or method in isolation, but not part of the specification contract.
    - integration: Tests how multiple features interact.
    - edge: An obscure corner case, bug reported in the wild, or something added to get full test coverage.

"""
  if contract_change or test_change:
    prompt += "Return the full test plan (including untouched tests) as JSON array using the provided schema."
  elif existing:
    prompt += "Return any new tests as JSON array using the provided schema. Empty if no new tests are required."
  else:
    prompt += "Return the full test plan as JSON array using the provided schema."

  existingTestNames = [t["name"] for t in existing_tests]
  existingTestTypes = {(t["name"], t["type"]) for t in existing_tests}
  existingTestDescriptions = {(t["name"], t["description"]) for t in existing_tests}
  existingTestPseudocode = {(t["name"], t["pseudocode"]) for t in existing_tests}

  timeout = 10
  while timeout > 0:
    timeout -= 1
    result = json.loads(llm.chat_structured(prompt, TEST_SCHEMA))
    new_tests = []
    if result:
      new_tests = result

    if not new_tests:
      return _package_tests(existing_tests, hashCode)

    newTestNames = [t["name"] for t in new_tests]
    newTestTypes = {(t["name"], t["type"]) for t in new_tests}
    newTestDescriptions = {(t["name"], t["description"]) for t in new_tests}
    newTestPseudocode = {(t["name"], t["pseudocode"]) for t in new_tests}

    errors = set()

    for t in new_tests:
      if t["name"] == "":
        errors.add("There's an empty test name.")
        continue
      if t["description"] == "":
        errors.add(f"Test {t['name']} has an empty description.")
      if len(t["pseudocode"]) < 10:
        errors.add(f"Test {t['name']} has pseudocode that is too short to be useful.")

      if newTestNames.count(t["name"]) > 1:
        errors.add(f"Test {t['name']} is duplicated.")

    if existing and not contract_change and not test_change:
      # Adding new tests
      for t in new_tests:
        if existingTestNames.count(t["name"]) > 0:
          errors.add(f"Test {t['name']} already exists.")

      if not errors:
        for t in new_tests:
          print("New test added " + t["type"] + ": " + t["name"] + " - " + t["description"])
        tests = existing_tests + new_tests
        return _package_tests(tests, hashCode)
      else:
        prompt = "\n".join(errors)
        print("LLM failed to extend the test plan. Retrying...")
        #print("\n -".join(errors))
        continue

    removedTests = set(existingTestNames) - set(newTestNames)
    newTests = set(newTestNames) - set(existingTestNames)
    commonTests = set(existingTestNames) & set(newTestNames)

    for rt in removedTests:
      if existingTestTypes[rt["name"]] == "contract" and not contract_change:
        errors.add(f"Test {rt['name']} is a contract test and cannot be removed.")
      if not test_change:
        errors.add(f"Test {rt['name']} cannot be removed.")

    for ct in commonTests:
      if existingTestTypes[ct["name"]] == "contract" and not contract_change:
        if existingTestDescriptions[ct["name"]] != newTestDescriptions[ct["name"]]:
          errors.add(
            f"Test {ct['name']} is a contract test and cannot have its description changed.")
        if existingTestPseudocode[ct["name"]] != newTestPseudocode[ct["name"]]:
          errors.add(
            f"Test {ct['name']} is a contract test and cannot have its pseudocode changed.")
        if existingTestTypes[ct["name"]] != newTestTypes[ct["name"]]:
          errors.add(f"Test {ct['name']} is a contract test and cannot have its type changed.")

      if not test_change:
        if existingTestDescriptions[ct["name"]] != newTestDescriptions[ct["name"]]:
          errors.add(f"Test {ct['name']} cannot have its description changed.")
        if existingTestPseudocode[ct["name"]] != newTestPseudocode[ct["name"]]:
          errors.add(f"Test {ct['name']} cannot have its pseudocode changed.")
        if existingTestTypes[ct["name"]] != newTestTypes[ct["name"]]:
          errors.add(f"Test {ct['name']} cannot have its type changed.")

    if not errors:
      for n in newTests:
        print("New test added " + newTestTypes[n] + ": " + n + " - " + newTestDescriptions[n])
      tests = existing_tests + new_tests
      return _package_tests(tests, hashCode)
    else:
      prompt = "\n".join(errors)
      if existing:
        print("LLM failed to revise the test plan cleanly. Retrying...")
      else:
        print("LLM failed to generate a test plan. Retrying...")
      #print("\n -".join(errors))
      continue

  print("Compilation failed - LLM was unable to generate a valid test plan")
  return None
