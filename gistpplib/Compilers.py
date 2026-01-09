from abc import ABC, abstractmethod


class Compiler(ABC):

  @abstractmethod
  def compile(self) -> (bool, str):
    pass


def CompilerFactory(output_type: OutputType, spec_content: str, spec_db: MarkdownDocument,
                    build_dir: str) -> Compiler:
  return Compiler()
