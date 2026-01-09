from gistpplib.markdown_db import MarkdownDocument, NodeType

from .Constants import *


class GistPPParser:

    def __init__(self, spec_content: MarkdownDocument):
        self.spec_content = spec_content

        title = spec_content.Children[0].Text

        for tt in target_types:
            if tt.lower() in title.lower():
                self.target_type = tt
                break
        else:
            print("Unknown target type? Title should contain one of " +
                  ", ".join(target_types))
            raise ValueError("Unknown target type")

        subHeadings = {}

        self.intro = ""

        for c in spec_content.Children[0].Children:
            if c.Type == NodeType.Paragraph:
                self.intro += c.Text
            else:
                subHeadings[c.Text] = c

        self.behavior = subHeadings["Behavior"].Children

        self.dependencies = subHeadings[
            "Dependencies"].Children if "Dependencies" in subHeadings else []

        self.tests = subHeadings[
            "Tests"].Children if "Tests" in subHeadings else []
