from pathlib import Path


SUPPORTED_SUFFIXES = {".md", ".txt"}


def load_knowledge_files(knowledge_dir: str) -> list[dict]:
    base_dir = Path(knowledge_dir)
    if not base_dir.exists() or not base_dir.is_dir():
        return []

    documents: list[dict] = []
    for file_path in sorted(base_dir.rglob("*")):
        if not file_path.is_file() or file_path.suffix.lower() not in SUPPORTED_SUFFIXES:
            continue

        content = file_path.read_text(encoding="utf-8").strip()
        if not content:
            continue

        documents.append(
            {
                "content": content,
                "source": file_path.as_posix(),
            }
        )

    return documents
