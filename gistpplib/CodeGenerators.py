from abc import ABC, abstractmethod


class CodeGenerator(ABC):

  @abstractmethod
  def generateTests(self) -> str:
    pass

  @abstractmethod
  def generateCode(self, incremental: bool) -> str:
    pass

  @abstractmethod
  def feedback(self, message: str, source: str) -> str:
    pass


def CodeGeneratorFactory(
  output_type: OutputType,
  spec_content: str,
  spec_db: MarkdownDocument,
  interface: Interface,
  test_plan: TestPlan,
  dependancies: dict,
  build_dir: str,
) -> CodeGenerator:
  return CodeGenerator()
