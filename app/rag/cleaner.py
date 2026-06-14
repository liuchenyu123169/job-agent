import re


HEADING_PREFIX_RE = re.compile(r"^\s{0,3}#{1,6}\s+")
BOLD_ITALIC_RE = re.compile(r"(\*\*\*|\*\*|\*|___|__|_)")
INLINE_CODE_RE = re.compile(r"`([^`]*)`")
LIST_PREFIX_RE = re.compile(
    r"^\s*([-+*]|\d+[.)]|\d+[\u3001.\uff0e]|[\u4e00-\u5341]+[\u3001.\uff0e])\s+"
)
BLOCKQUOTE_RE = re.compile(r"^\s*>\s?")
MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")
IMAGE_RE = re.compile(r"!\[([^\]]*)\]\([^)]+\)")
SEPARATOR_RE = re.compile(r"^\s*[-=*_]{3,}\s*$")
CODE_FENCE_RE = re.compile(r"^\s*```")


def clean_markdown_text(text: str) -> str:
    if not text:
        return ""

    cleaned_lines: list[str] = []
    in_code_block = False

    for raw_line in text.splitlines():
        line = raw_line.rstrip()

        if CODE_FENCE_RE.match(line):
            in_code_block = not in_code_block
            continue

        if in_code_block or SEPARATOR_RE.match(line):
            continue

        line = HEADING_PREFIX_RE.sub("", line)
        line = BLOCKQUOTE_RE.sub("", line)
        line = LIST_PREFIX_RE.sub("", line)
        line = IMAGE_RE.sub(r"\1", line)
        line = MARKDOWN_LINK_RE.sub(r"\1", line)
        line = INLINE_CODE_RE.sub(r"\1", line)
        line = BOLD_ITALIC_RE.sub("", line)
        line = re.sub(r"<[^>]+>", "", line)
        line = re.sub(r"\s+", " ", line).strip()

        if line:
            cleaned_lines.append(line)

    return "\n".join(cleaned_lines).strip()
