# markdown_db.py
from __future__ import annotations

import os
import re
from enum import Enum
from pathlib import Path
from typing import Iterator, List, Optional, Sequence, TextIO, Union


class NodeType(Enum):
    Root = "Root"
    Heading1 = "Heading1"
    Heading2 = "Heading2"
    Heading3 = "Heading3"
    Heading4 = "Heading4"
    Heading5 = "Heading5"
    Heading6 = "Heading6"
    Paragraph = "Paragraph"
    Text = "Text"
    Link = "Link"
    Image = "Image"
    CodeBlock = "CodeBlock"
    BlockQuote = "BlockQuote"
    List = "List"
    ListItem = "ListItem"
    Raw = "Raw"


_HEADING_TYPES = {i: getattr(NodeType, f"Heading{i}") for i in range(1, 7)}


def _strip_linebreaks_only(text: str) -> str:
    return text.rstrip("\r\n")


def _split_trivia(raw: str) -> tuple[str, str, str]:
    # (leading whitespace, core, trailing whitespace). \s includes newlines.
    m = re.match(r"(\s*)(.*?)(\s*)\Z", raw, flags=re.DOTALL)
    if not m:
        return "", raw, ""
    return m.group(1), m.group(2), m.group(3)


class MarkdownNode:

    def __init__(self,
                 node_type: NodeType,
                 *,
                 parent: Optional["MarkdownNode"] = None) -> None:
        self.Type: NodeType = node_type
        self._parent: Optional["MarkdownNode"] = parent
        self._children: List["MarkdownNode"] = []
        self._dirty_self: bool = False

    # Container behaviour
    def __iter__(self) -> Iterator["MarkdownNode"]:
        return iter(self._children)

    def __len__(self) -> int:
        return len(self._children)

    def __getitem__(self, idx: int) -> "MarkdownNode":
        return self._children[idx]

    @property
    def Parent(self) -> Optional["MarkdownNode"]:
        return self._parent

    @property
    def Children(self) -> Sequence["MarkdownNode"]:
        return self._children

    # Programmatic edits: mark dirty
    def AddChild(self, child: "MarkdownNode") -> None:
        child._parent = self
        self._children.append(child)
        self.MarkDirty()

    # Parser attach: do not mark dirty
    def _AppendChildParsed(self, child: "MarkdownNode") -> None:
        child._parent = self
        self._children.append(child)

    def Walk(self) -> Iterator["MarkdownNode"]:
        yield self
        for child in self._children:
            yield from child.Walk()

    def FindAll(self, node_type: NodeType) -> Iterator["MarkdownNode"]:
        for node in self.Walk():
            if node.Type == node_type:
                yield node

    @property
    def IsDirty(self) -> bool:
        if self._dirty_self:
            return True
        return any(c.IsDirty for c in self._children)

    def MarkDirty(self) -> None:
        self._dirty_self = True

    # Text API (override in nodes that have it)
    @property
    def Text(self) -> str:
        return ""

    @Text.setter
    def Text(self, value: str) -> None:
        raise AttributeError(
            f"{self.Type.value} does not support Text assignment")

    # Serialisation
    def ToMarkdown(self) -> str:
        return "".join(child.ToMarkdown() for child in self._children)

    def ToString(self) -> str:
        return _strip_linebreaks_only(self.ToMarkdown())

    def ToPlainText(self) -> str:
        return self.ToString()

    def SaveToString(self) -> str:
        return self.ToMarkdown()

    def SaveToStream(self, stream: TextIO) -> None:
        stream.write(self.ToMarkdown())

    def SaveToFile(self,
                   path: Union[str, os.PathLike],
                   *,
                   encoding: str = "utf-8") -> None:
        Path(path).write_text(self.ToMarkdown(), encoding=encoding)


class TextNode(MarkdownNode):

    def __init__(self,
                 raw: str,
                 *,
                 parent: Optional[MarkdownNode] = None) -> None:
        super().__init__(NodeType.Text, parent=parent)
        self._raw_original: str = raw
        self._leading, self._core, self._trailing = _split_trivia(raw)

    @property
    def Text(self) -> str:
        return self._core

    @Text.setter
    def Text(self, value: str) -> None:
        self._core = value.strip()
        self.MarkDirty()

    def ToMarkdown(self) -> str:
        if not self.IsDirty:
            return self._raw_original
        return f"{self._leading}{self._core}{self._trailing}"

    def ToPlainText(self) -> str:
        return self.ToMarkdown()


class LinkNode(MarkdownNode):

    def __init__(self,
                 raw: str,
                 label: str,
                 href: str,
                 *,
                 parent: Optional[MarkdownNode] = None,
                 is_image: bool = False) -> None:
        super().__init__(NodeType.Image if is_image else NodeType.Link,
                         parent=parent)
        self._raw_original: str = raw
        self._is_image: bool = is_image

        self._label_leading, self._label_core, self._label_trailing = _split_trivia(
            label)
        self._href_leading, self._href_core, self._href_trailing = _split_trivia(
            href)

    @property
    def Text(self) -> str:
        return self._label_core

    @Text.setter
    def Text(self, value: str) -> None:
        self._label_core = value.strip()
        self.MarkDirty()

    @property
    def Href(self) -> str:
        return self._href_core

    @Href.setter
    def Href(self, value: str) -> None:
        self._href_core = value.strip()
        self.MarkDirty()

    def ToMarkdown(self) -> str:
        if not self.IsDirty:
            return self._raw_original
        bang = "!" if self._is_image else ""
        label = f"{self._label_leading}{self._label_core}{self._label_trailing}"
        href = f"{self._href_leading}{self._href_core}{self._href_trailing}"
        return f"{bang}[{label}]({href})"

    def ToPlainText(self) -> str:
        return f"{self._label_leading}{self._label_core}{self._label_trailing}"


class CodeBlockNode(MarkdownNode):
    """
    Fenced code block (``` or ~~~).
    Stored losslessly; editable via Text (code body) and InfoString.
    """

    def __init__(self,
                 opening_line: str,
                 code_body: str,
                 closing_line: str,
                 block_suffix: str,
                 *,
                 parent: Optional[MarkdownNode] = None) -> None:
        super().__init__(NodeType.CodeBlock, parent=parent)
        self._opening_line_original = opening_line
        self._closing_line_original = closing_line
        self._block_suffix_original = block_suffix

        self._opening_prefix, self._fence, self._info, self._opening_eol = self._parse_opening(
            opening_line)
        self._closing_indent, self._closing_fence, self._closing_trailing, self._closing_eol = self._parse_closing(
            closing_line)

        self._code_body_original = code_body
        self._code_body_current = code_body

    @staticmethod
    def _parse_opening(line: str) -> tuple[str, str, str, str]:
        m = re.match(
            r"^(?P<indent>[ \t]*)(?P<fence>`{3,}|~{3,})(?P<info>[^\r\n]*?)(?P<eol>\r?\n)?\Z",
            line)
        if not m:
            return "", "```", "", "\n" if line.endswith("\n") else ""
        return m.group("indent"), m.group("fence"), m.group(
            "info"), m.group("eol") or ""

    @staticmethod
    def _parse_closing(line: str) -> tuple[str, str, str, str]:
        m = re.match(
            r"^(?P<indent>[ \t]*)(?P<fence>`{3,}|~{3,})(?P<trailing>[^\r\n]*?)(?P<eol>\r?\n)?\Z",
            line)
        if not m:
            return "", "```", "", "\n" if line.endswith("\n") else ""
        return m.group("indent"), m.group("fence"), m.group(
            "trailing"), m.group("eol") or ""

    @property
    def Text(self) -> str:
        return self._code_body_current

    @Text.setter
    def Text(self, value: str) -> None:
        self._code_body_current = value
        self.MarkDirty()

    @property
    def InfoString(self) -> str:
        return self._info.strip()

    @InfoString.setter
    def InfoString(self, value: str) -> None:
        self._info = " " + value.strip() if value.strip() else ""
        self.MarkDirty()

    def ToMarkdown(self) -> str:
        if not self.IsDirty:
            return (self._opening_line_original + self._code_body_original +
                    self._closing_line_original + self._block_suffix_original)

        opening = f"{self._opening_prefix}{self._fence}{self._info}{self._opening_eol}"
        closing = f"{self._closing_indent}{self._closing_fence}{self._closing_trailing}{self._closing_eol}"
        return opening + self._code_body_current + closing + self._block_suffix_original


class HeadingNode(MarkdownNode):

    def __init__(
        self,
        level: int,
        raw_line: str,
        prefix: str,
        title_raw: str,
        line_suffix: str,
        block_suffix: str,
        *,
        parent: Optional[MarkdownNode] = None,
    ) -> None:
        super().__init__(_HEADING_TYPES[level], parent=parent)
        self.Level = level

        self._raw_line_original = raw_line
        self._prefix = prefix
        self._title_leading, self._title_core, self._title_trailing = _split_trivia(
            title_raw)
        self._line_suffix = line_suffix
        self._block_suffix = block_suffix

    @property
    def Text(self) -> str:
        return self._title_core

    @Text.setter
    def Text(self, value: str) -> None:
        self._title_core = value.strip()
        self.MarkDirty()

    def ToMarkdown(self) -> str:
        if not self._dirty_self:
            line = self._raw_line_original
        else:
            title = f"{self._title_leading}{self._title_core}{self._title_trailing}"
            line = f"{self._prefix}{title}{self._line_suffix}"
        return line + self._block_suffix + "".join(child.ToMarkdown()
                                                   for child in self._children)


def _try_parse_link(raw: str, pos: int, *,
                    is_image: bool) -> Optional[tuple[int, int, str, str]]:
    start = pos
    if is_image:
        if not raw.startswith("![", pos):
            return None
        label_start = pos + 2
    else:
        if raw[pos] != "[":
            return None
        label_start = pos + 1

    close_bracket = raw.find("]", label_start)
    if close_bracket == -1:
        return None
    if close_bracket + 1 >= len(raw) or raw[close_bracket + 1] != "(":
        return None

    href_start = close_bracket + 2
    close_paren = raw.find(")", href_start)
    if close_paren == -1:
        return None

    end = close_paren + 1
    label = raw[label_start:close_bracket]
    href = raw[href_start:close_paren]
    return (start, end, label, href)


def _parse_inlines(raw: str) -> List[MarkdownNode]:
    nodes: List[MarkdownNode] = []
    buffer_start = 0
    i = 0

    def flush_text(until: int) -> None:
        nonlocal buffer_start
        if until > buffer_start:
            nodes.append(TextNode(raw[buffer_start:until]))
        buffer_start = until

    while i < len(raw):
        if raw.startswith("![", i):
            parsed = _try_parse_link(raw, i, is_image=True)
            if parsed:
                start, end, label, href = parsed
                flush_text(start)
                nodes.append(
                    LinkNode(raw[start:end], label, href, is_image=True))
                i = end
                buffer_start = i
                continue

        if raw[i] == "[":
            parsed = _try_parse_link(raw, i, is_image=False)
            if parsed:
                start, end, label, href = parsed
                flush_text(start)
                nodes.append(
                    LinkNode(raw[start:end], label, href, is_image=False))
                i = end
                buffer_start = i
                continue

        i += 1

    flush_text(len(raw))
    return nodes


class ParagraphNode(MarkdownNode):

    def __init__(self,
                 raw_content: str,
                 block_suffix: str,
                 *,
                 parent: Optional[MarkdownNode] = None) -> None:
        super().__init__(NodeType.Paragraph, parent=parent)
        self._raw_original = raw_content
        self._block_suffix = block_suffix
        self._children = _parse_inlines(raw_content)
        for c in self._children:
            c._parent = self

    @property
    def Text(self) -> str:
        plain = "".join(child.ToPlainText() for child in self._children)
        return plain.strip()

    def ToMarkdown(self) -> str:
        if not self._dirty_self and not any(c.IsDirty for c in self._children):
            content = self._raw_original
        else:
            content = "".join(child.ToMarkdown() for child in self._children)
        return content + self._block_suffix


class MarkdownDocument(MarkdownNode):

    def __init__(self,
                 markdown: str = "",
                 *,
                 source_path: Optional[str] = None) -> None:
        super().__init__(NodeType.Root, parent=None)
        self._leading_trivia: str = ""
        self._source_path = source_path
        if markdown:
            self.Parse(markdown)

    @classmethod
    def FromString(cls, markdown: str) -> "MarkdownDocument":
        return cls(markdown)

    @classmethod
    def FromFile(cls,
                 path: Union[str, os.PathLike],
                 *,
                 encoding: str = "utf-8") -> "MarkdownDocument":
        p = Path(path)
        return cls(p.read_text(encoding=encoding), source_path=str(p))

    @classmethod
    def FromStream(cls, stream: TextIO) -> "MarkdownDocument":
        return cls(stream.read())

    def Parse(self, markdown: str) -> None:
        self._children.clear()
        self._leading_trivia = ""

        lines = markdown.splitlines(keepends=True)
        i = 0

        blank_line_re = re.compile(r"^[ \t]*\r?\n\Z")
        heading_re = re.compile(
            r"^(?P<indent>[ \t]*)(?P<hashes>#{1,6})(?P<space>[ \t]+)(?P<title>.*?)(?P<trailing>[ \t]*)(?P<eol>\r?\n)?\Z"
        )
        fence_open_re = re.compile(
            r"^(?P<indent>[ \t]*)(?P<fence>`{3,}|~{3,})(?P<info>[^\r\n]*)(?P<eol>\r?\n)?\Z"
        )

        def is_blank(line: str) -> bool:
            return bool(blank_line_re.match(line))

        def heading_match(line: str) -> Optional[re.Match]:
            return heading_re.match(line)

        def fence_open_match(line: str) -> Optional[re.Match]:
            return fence_open_re.match(line)

        while i < len(lines) and is_blank(lines[i]):
            self._leading_trivia += lines[i]
            i += 1

        stack: List[MarkdownNode] = [self]
        stack_levels: List[int] = [0]

        while i < len(lines):
            line = lines[i]

            # Code fence
            fm = fence_open_match(line)
            if fm:
                opening_line = line
                fence = fm.group("fence")
                fence_char = fence[0]
                fence_len = len(fence)
                i += 1

                body_lines: List[str] = []
                closing_line = ""
                while i < len(lines):
                    l2 = lines[i]
                    mclose = re.match(
                        rf"^[ \t]*{re.escape(fence_char)}{{{fence_len},}}[ \t]*[^\r\n]*\r?\n?\Z",
                        l2,
                    )
                    if mclose:
                        closing_line = l2
                        i += 1
                        break
                    body_lines.append(l2)
                    i += 1

                if closing_line != "":
                    code_body = "".join(body_lines)
                    block_suffix = ""
                    while i < len(lines) and is_blank(lines[i]):
                        block_suffix += lines[i]
                        i += 1
                    stack[-1]._AppendChildParsed(
                        CodeBlockNode(opening_line, code_body, closing_line,
                                      block_suffix))
                    continue

                # No closing fence: rewind and parse as paragraph
                i = i - len(body_lines) - 1
                line = lines[i]

            # Heading
            hm = heading_match(line)
            if hm:
                level = len(hm.group("hashes"))
                prefix = hm.group("indent") + hm.group("hashes") + hm.group(
                    "space")
                title_raw = hm.group("title")
                line_suffix = hm.group("trailing") + (hm.group("eol") or "")
                raw_line = line
                i += 1

                block_suffix = ""
                while i < len(lines) and is_blank(lines[i]):
                    block_suffix += lines[i]
                    i += 1

                while stack_levels and stack_levels[-1] >= level:
                    stack.pop()
                    stack_levels.pop()

                parent = stack[-1]
                heading_node = HeadingNode(level, raw_line, prefix, title_raw,
                                           line_suffix, block_suffix)
                parent._AppendChildParsed(heading_node)

                stack.append(heading_node)
                stack_levels.append(level)
                continue

            # Paragraph
            para_lines: List[str] = [line]
            i += 1
            while i < len(lines):
                if is_blank(lines[i]):
                    break
                if heading_match(lines[i]):
                    break
                if fence_open_match(lines[i]):
                    break
                para_lines.append(lines[i])
                i += 1

            raw_para = "".join(para_lines)
            block_suffix = ""
            while i < len(lines) and is_blank(lines[i]):
                block_suffix += lines[i]
                i += 1

            stack[-1]._AppendChildParsed(ParagraphNode(raw_para, block_suffix))

    def ToMarkdown(self) -> str:
        return self._leading_trivia + "".join(child.ToMarkdown()
                                              for child in self._children)
