from abc import ABC, abstractmethod


class TestHarness(ABC):

  @abstractmethod
  def runTests(self) -> (bool, str):
    pass


def TestHarnessFactory(output_type: OutputType, spec_content: str, spec_db: MarkdownDocument,
                       test_plan: TestPlan, build_dir: str) -> TestHarness:
  return TestHarness()
