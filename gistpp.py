import argparse, gistpplib, os, sys

if __name__ == "__main__":
  parser = argparse.ArgumentParser(description="GistPP - Generate code from markdown")
  parser.add_argument("input", type=str, help="Input markdown file")
  parser.add_argument("output", type=str, help="Output directory")
  parser.add_argument("-i,--interface-change",
                      type=bool,
                      default=False,
                      action="store_true",
                      help="Allow interface changes")
  parser.add_argument("-t,--test-change",
                      type=bool,
                      default=False,
                      action="store_true",
                      help="Allow non-contract test changes")
  parser.add_argument("-T,--contract-test-change",
                      type=bool,
                      default=False,
                      action="store_true",
                      help="Allow contract test changes")

  args = parser.parse_args()

  if not os.path.exists(args.input):
    print("Input file does not exist")
    exit(1)

  if not args.input.endswith(".gistpp"):
    print("Input file must be a gistpp file")
    exit(1)

  f = open(args.input, "r")
  spec_content = f.read()
  f.close()

  if not gistpplib.validate(spec_content, "gistpp"):
    print("Exiting due to invalid spec file: " + args.input)
    exit(1)

  interfaceFile = args.input.replace(".gistpp", ".interface")
  testsFile = args.input.replace(".gistpp", ".tests")

  try:
    spec_db = gistpplib.MarkdownDocument(spec_content)
    parsed = gistpplib.GistPPParser(spec_db)
  except ValueError as e:
    print("Exiting due to invalid spec file: " + args.input)
    exit(1)

  llmSession = None

  def lazy_llm_session():
    global llmSession
    if llmSession is None:
      llmSession = gistpplib.llm_factory.LlmFactory()
    return llmSession

  ##### Interface Generation #####

  if not os.path.exists(interfaceFile):
    print("First run - generating interface...")
    interface = gistpplib.generate_interface(parsed, spec_content, "", lazy_llm_session())
    f = open(interfaceFile, "w")
    f.write(interface)
    f.close()
  elif args.interface_change:
    print("Interface change allowed. Checking for changes...")
    interface_content = open(interfaceFile, "r").read()

    interface = gistpplib.generate_interface(parsed, spec_content, interface_content,
                                             lazy_llm_session())
    f = open(interfaceFile, "w")
    f.write(interface)
    f.close()

  interface_content = open(interfaceFile, "r").read()
  if not gistpplib.validate(interface_content, "interface"):
    print("Exiting due to invalid interface")
    exit(1)

  ##### Test Generation #####
  print("Generating tests...")

  testsWritten = False

  if not os.path.exists(testsFile):
    print("First run - generating tests")
    tests = gistpplib.generate_tests(parsed, spec_content, "[]", True, interface_content,
                                     lazy_llm_session())
    if tests is None:
      exit(1)
    f = open(testsFile, "w")
    f.write(tests)
    f.close()
    testsWritten = True
  elif args.test_change or args.contract_test_change:
    print("Test changes allowed.")
    tests = open(testsFile, "r").read()
    tests = gistpplib.generate_tests(parsed, spec_content, tests,
                                     (args.test_change, args.contract_test_change),
                                     interface_content, lazy_llm_session())
    if tests is None:
      exit(1)
    f = open(testsFile, "w")
    f.write(tests)
    f.close()
    testsWritten = True

  ### Dependancy Resolution ###
  print("Resolving dependancies...")

  for d in parsed.dependencies:
    pass  #NYI

  ### Code Generation ###
  print("Generating code...")

  codeGen = gistpplib.CodeGeneratorFactory(parsed.output_type, spec_content, spec_db,
                                           interface_content, testsFile, parsed.dependencies,
                                           args.build_dir)
  codeGen.generateCode(incremental=bool(existing))

  if testsWritten:
    codeGen.generateTests()

  ### Compilation ###
  print("Compiling code...")

  compiler = gistpplib.CompilerFactory(parsed.output_type, spec_content, spec_db, args.build_dir)

  compileCount = 10
  while compileCount > 0:
    compileCount -= 1
    success, message = compiler.compile()
    if success:
      break

    if compileCount == 0:
      print("Compilation failed: Generated code isn't compiling after 10 attempts")
      print(message)
      exit(1)

    codeGen.feedback(message, "Compile")

  ### Test Running ###
  print("Running tests...")

  testHarness = gistpplib.TestHarnessFactory(parsed.output_type, spec_content, spec_db,
                                             parsed.tests, args.build_dir)

  testCount = 10
  while testCount > 0:
    testCount -= 1
    success, message = testHarness.runTests()
    if success:
      break

    if testCount == 0:
      print("Tests failed: Generated code isn't passing tests after 10 attempts")
      print(message)
      exit(1)

    codeGen.feedback(message, "Tests")

  print("Success")
