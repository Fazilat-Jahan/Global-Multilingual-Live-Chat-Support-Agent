import re


def clean_text(text: str) -> str:
    """Normalize whitespace and strip markdown heading markers."""
    text = text.replace("\r\n", "\n")
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def chunk_text(text: str, chunk_size: int = 800, chunk_overlap: int = 100) -> list[str]:
    """Split cleaned text into overlapping chunks, breaking on paragraph
    boundaries where possible so a chunk doesn't cut a sentence in half.
    """
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]

    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        candidate = f"{current}\n\n{paragraph}".strip() if current else paragraph
        if len(candidate) <= chunk_size:
            current = candidate
            continue

        if current:
            chunks.append(current)
        if len(paragraph) <= chunk_size:
            current = paragraph
        else:
            # Paragraph itself exceeds chunk_size — hard-split it.
            for i in range(0, len(paragraph), chunk_size - chunk_overlap):
                chunks.append(paragraph[i : i + chunk_size])
            current = ""

    if current:
        chunks.append(current)

    # Apply overlap between consecutive chunks for better retrieval context.
    if chunk_overlap > 0 and len(chunks) > 1:
        overlapped = [chunks[0]]
        for i in range(1, len(chunks)):
            prev_tail = chunks[i - 1][-chunk_overlap:]
            overlapped.append(f"{prev_tail} {chunks[i]}".strip())
        chunks = overlapped

    return chunks
