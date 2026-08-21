from backend.rag.chunking import chunk_text, clean_text


def test_clean_text_strips_markdown_headings():
    raw = "## What is your return window?\n\nYou can return items within 30 days."
    cleaned = clean_text(raw)
    assert "##" not in cleaned
    assert "What is your return window?" in cleaned


def test_clean_text_normalizes_whitespace_and_blank_lines():
    raw = "Line one.\r\n\r\n\r\n\r\nLine   two   with\textra\tspacing."
    cleaned = clean_text(raw)
    assert "\r" not in cleaned
    assert "\n\n\n" not in cleaned
    assert "  " not in cleaned


def test_chunk_text_respects_chunk_size():
    paragraph = "Sentence. " * 200  # far longer than any reasonable chunk_size
    chunks = chunk_text(paragraph, chunk_size=100, chunk_overlap=20)
    assert len(chunks) > 1
    for chunk in chunks:
        # allow the overlap prefix to push slightly past chunk_size
        assert len(chunk) <= 100 + 20 + 1


def test_chunk_text_keeps_short_text_as_one_chunk():
    text = "This is a short FAQ answer that fits in a single chunk."
    chunks = chunk_text(text, chunk_size=800, chunk_overlap=100)
    assert chunks == [text]


def test_chunk_text_overlap_carries_context_between_chunks():
    paragraphs = "\n\n".join(f"Paragraph number {i} with some filler content." for i in range(20))
    chunks = chunk_text(paragraphs, chunk_size=150, chunk_overlap=30)
    assert len(chunks) > 1
    # Every chunk after the first should start with a tail carried over from
    # the previous chunk (the overlap), not a clean paragraph boundary.
    for prev, curr in zip(chunks, chunks[1:]):
        assert curr.startswith(prev[-30:])
