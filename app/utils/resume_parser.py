from io import BytesIO

from docx import Document
from pypdf import PdfReader


def parse_resume_file(file_bytes: bytes, filename: str) -> str:
    if not file_bytes:
        raise ValueError("Uploaded file is empty")

    lower_name = filename.lower()

    if lower_name.endswith(".pdf"):
        text = _parse_pdf(file_bytes)
    elif lower_name.endswith(".docx"):
        text = _parse_docx(file_bytes)
    elif lower_name.endswith(".txt"):
        text = file_bytes.decode("utf-8")
    else:
        raise ValueError("Unsupported file type")

    cleaned_text = text.strip()
    if not cleaned_text:
        raise ValueError("Parsed resume content is empty")
    return cleaned_text


def _parse_pdf(file_bytes: bytes) -> str:
    reader = PdfReader(BytesIO(file_bytes))
    parts: list[str] = []
    for page in reader.pages:
        parts.append(page.extract_text() or "")
    return "\n".join(parts)


def _parse_docx(file_bytes: bytes) -> str:
    document = Document(BytesIO(file_bytes))
    parts = [paragraph.text for paragraph in document.paragraphs]
    return "\n".join(parts)
