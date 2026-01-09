from .markdown_db import *
from pymarkdown.api import PyMarkdownApi, PyMarkdownApiException


def validate(spec_content: str, file_type: str) -> bool:
    try:
        api = PyMarkdownApi()
        result = api.scan_string(spec_content)
    except PyMarkdownApiException as e:
        print(e)
        return False

    if result.critical_errors:
        print(result.critical_errors)
        return False

    if result.scan_failures:
        for sf in result.scan_failures:
            print(f"""
Error: {sf.rule_name} - {sf.rule_description}
Line: {sf.line_number}
Column: {sf.column_number}
            """.strip())

        return False

    if result.pragma_errors:
        print(result.pragma_errors)
        return False

    def reportError(message: str):
        print(message)
        return False

    if file_type == "gistpp":
        spec_db = MarkdownDocument(spec_content)

        assert len(spec_db.Children) == 1, "mardownlint should guarentee this"
        assert spec_db.Children[
            0].Type == NodeType.Heading1, "mardownlint should guarentee this"

        allowedh2 = ["Behavior", "Tests", "Dependencies"]
        subHeadings = {}

        for c in spec_db.Children[0].Children:
            if c.Type == NodeType.Paragraph:
                continue
            if c.Type != NodeType.Heading2:
                reportError(
                    "GistPP File layout, only text and heading 2 inside heading 1"
                )
                return False

            if c.Text in allowedh2:
                subHeadings[c.Text] = c
            else:
                reportError("Invalid heading 2: " + c.Text + " Only " +
                            ", ".join(allowedh2) + " allowed")
                return False

        if "Behavior" not in subHeadings:
            reportError("All gistpp files must have a Behavior heading2")
            return False

        hasHeading3 = False
        hasList = False
        hasParagraph = False
        for bc in subHeadings["Behavior"].Children:
            if bc.Type == NodeType.Heading3:
                hasHeading3 = True
            elif bc.Type == NodeType.List:
                hasList = True
            elif bc.Type == NodeType.Paragraph:
                hasParagraph = True
            else:
                reportError("Invalid node type inside Behavior heading2: " +
                            bc.Type)
                return False

        if hasHeading3 and (hasList or hasParagraph):
            reportError(
                "Behavior heading2 must have either subheadings OR text. Not both."
            )
            return False

    return True
