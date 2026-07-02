import re

from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.ai.rag.cleaner import clean_markdown_text


MAX_HEADING_LINE_LENGTH = 80
MIN_CHUNK_CONTENT_LENGTH = 50
WEAK_BOUNDARY_MIN_LENGTH = 300
SECONDARY_CHUNK_MAX_LENGTH = 1000

MARKDOWN_HEADING_RE = re.compile(r"^\s{0,3}(#{1,6})\s+(.+)$")
CHINESE_NUMBERING_RE = re.compile(r"^([\u4e00-\u5341]+)[\u3001.\uff0e]\s*(.+)$")
CHINESE_PAREN_NUMBERING_RE = re.compile(r"^[\uff08(]([\u4e00-\u5341]+)[\uff09)]\s*(.+)$")
ARABIC_NUMBERING_RE = re.compile(r"^(\d+)[\u3001.\uff0e)\uff09]\s*(.+)$")
ARABIC_PAREN_NUMBERING_RE = re.compile(r"^[\uff08(](\d+)[\uff09)]\s*(.+)$")
SPECIAL_BRACKET_TITLE_RE = re.compile(
    r"^[\u3010\u300a\u300c\u300e](.+)[\u3011\u300b\u300d\u300f]\s*$"
)
QA_TITLE_RE = re.compile(
    r"^(Q[:\uff1a]|\u95ee\u9898[:\uff1a]|\u9762\u8bd5\u9898[:\uff1a]|\u95ee[:\uff1a])\s*(.+)$",
    re.IGNORECASE,
)
SHORT_COLON_TITLE_RE = re.compile(r"^(.{2,40})[:\uff1a]\s*$")
SEPARATOR_RE = re.compile(r"^\s*[-=*_]{3,}\s*$")
CODE_FENCE_RE = re.compile(r"^\s*```")

FALLBACK_SPLITTER = RecursiveCharacterTextSplitter(
    chunk_size=800,
    chunk_overlap=100,
    separators=[
        "\n\n",
        "\n",
        "\u3002",
        "\uff01",
        "\uff1f",
        ".",
        "!",
        "?",
        "\uff1b",
        ";",
        " ",
        "",
    ],
)


def is_heading_line(line: str) -> bool:
    return _parse_heading(line) is not None


def extract_title(line: str) -> str:
    heading = _parse_heading(line)
    if heading is None:
        return _normalize_title(line.strip())
    return heading["title"]


def split_by_structural_headings(text: str, source: str) -> list[dict]:
    lines = text.splitlines()
    chunks: list[dict] = []
    heading_stack: list[dict] = []
    current_chunk: dict | None = None
    current_body_lines: list[str] = []
    in_code_block = False
    found_heading = False

    def flush_chunk(force: bool = False) -> None:
        nonlocal current_chunk, current_body_lines
        if current_chunk is None:
            return

        body_raw = "\n".join(current_body_lines).strip()
        body_clean = clean_markdown_text(body_raw)
        if force or _current_chunk_length(current_body_lines) > WEAK_BOUNDARY_MIN_LENGTH:
            chunk = _build_chunk(
                title=current_chunk["title"],
                body_clean=body_clean,
                section_path=current_chunk["section_path"],
                source=source,
            )
            if chunk:
                chunks.append(chunk)
            current_chunk = None
            current_body_lines = []

    for raw_line in lines:
        line = raw_line.rstrip()

        if CODE_FENCE_RE.match(line):
            if current_chunk is not None:
                current_body_lines.append(line)
            in_code_block = not in_code_block
            continue

        if in_code_block:
            if current_chunk is not None:
                current_body_lines.append(line)
            continue

        if SEPARATOR_RE.match(line.strip()):
            flush_chunk(force=False)
            continue

        heading = _parse_heading(line)
        if heading is not None:
            found_heading = True
            flush_chunk(force=True)
            while heading_stack and heading_stack[-1]["level"] >= heading["level"]:
                heading_stack.pop()
            section_path = " > ".join(item["title"] for item in heading_stack)
            current_chunk = {
                "title": heading["title"],
                "section_path": section_path,
            }
            current_body_lines = []
            heading_stack.append({"level": heading["level"], "title": heading["title"]})
            continue

        if current_chunk is not None:
            current_body_lines.append(line)

    flush_chunk(force=True)
    return chunks if found_heading else []


def split_documents(docs: list[dict]) -> list[dict]:
    if not docs:
        return []

    chunks: list[dict] = []
    chunk_index = 0

    for document in docs:
        source = document.get("source")
        text = document.get("content", "")
        structural_chunks = split_by_structural_headings(text, source)

        if not structural_chunks:
            structural_chunks = _fallback_split(text, source)

        for chunk in structural_chunks:
            for piece in _split_large_chunk(chunk):
                if len(piece["content"]) < MIN_CHUNK_CONTENT_LENGTH:
                    continue
                chunks.append(
                    {
                        "content": piece["content"],
                        "source": piece["source"],
                        "chunk_index": chunk_index,
                        "title": piece.get("title", ""),
                        "section_path": piece.get("section_path", ""),
                    }
                )
                chunk_index += 1

    return chunks


def _fallback_split(text: str, source: str) -> list[dict]:
    chunks: list[dict] = []
    for piece in FALLBACK_SPLITTER.split_text(text):
        cleaned_piece = clean_markdown_text(piece.strip())
        if len(cleaned_piece) < MIN_CHUNK_CONTENT_LENGTH:
            continue
        chunks.append(
            {
                "title": "",
                "content": cleaned_piece,
                "source": source,
                "section_path": "",
            }
        )
    return chunks


def _split_large_chunk(chunk: dict) -> list[dict]:
    content = chunk.get("content", "").strip()
    if not content:
        return []
    if len(content) <= SECONDARY_CHUNK_MAX_LENGTH:
        return [chunk]

    pieces: list[dict] = []
    for piece in FALLBACK_SPLITTER.split_text(content):
        cleaned_piece = clean_markdown_text(piece.strip())
        if len(cleaned_piece) < MIN_CHUNK_CONTENT_LENGTH:
            continue
        pieces.append(
            {
                "title": chunk.get("title", ""),
                "content": cleaned_piece,
                "source": chunk.get("source"),
                "section_path": chunk.get("section_path", ""),
            }
        )
    return pieces


def _build_chunk(title: str, body_clean: str, section_path: str, source: str) -> dict | None:
    title_clean = clean_markdown_text(title).strip()
    if not title_clean or not body_clean:
        return None

    content = f"{title_clean}\n{body_clean}".strip()
    if len(content) < MIN_CHUNK_CONTENT_LENGTH:
        return None

    return {
        "title": title_clean,
        "content": content,
        "source": source,
        "section_path": section_path,
    }


def _parse_heading(line: str) -> dict | None:
    stripped = line.strip()
    if not stripped or len(stripped) > MAX_HEADING_LINE_LENGTH:
        return None
    if SEPARATOR_RE.match(stripped):
        return None

    match = MARKDOWN_HEADING_RE.match(stripped)
    if match:
        title = _normalize_title(match.group(2))
        return {"level": len(match.group(1)), "title": title} if title else None

    match = CHINESE_NUMBERING_RE.match(stripped)
    if match:
        return _make_heading(2, match.group(2))

    match = CHINESE_PAREN_NUMBERING_RE.match(stripped)
    if match:
        return _make_heading(3, match.group(2))

    match = ARABIC_NUMBERING_RE.match(stripped)
    if match:
        return _make_heading(2, match.group(2))

    match = ARABIC_PAREN_NUMBERING_RE.match(stripped)
    if match:
        return _make_heading(3, match.group(1 if match.lastindex == 1 else 2))

    match = SPECIAL_BRACKET_TITLE_RE.match(stripped)
    if match:
        return _make_heading(2, match.group(1))

    match = QA_TITLE_RE.match(stripped)
    if match:
        return _make_heading(3, match.group(2))

    match = SHORT_COLON_TITLE_RE.match(stripped)
    if match and _is_short_colon_heading(stripped):
        return _make_heading(3, match.group(1))

    return None


def _make_heading(level: int, raw_title: str) -> dict | None:
    title = _normalize_title(raw_title)
    if not title:
        return None
    return {"level": level, "title": title}


def _is_short_colon_heading(line: str) -> bool:
    match = SHORT_COLON_TITLE_RE.match(line)
    if not match:
        return False

    prefix = match.group(1).strip()
    if len(prefix) > 40:
        return False
    if re.search(r"[\uff0c,\u3002\uff01\uff1f!?\uff1b;]", prefix):
        return False
    return True


def _normalize_title(title: str) -> str:
    return clean_markdown_text(title).strip("\uff1a: ").strip()


def _current_chunk_length(lines: list[str]) -> int:
    return len("\n".join(lines).strip())
