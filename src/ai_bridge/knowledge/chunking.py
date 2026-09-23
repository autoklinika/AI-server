from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MarkdownChunk:
    ordinal: int
    section: str
    text: str


@dataclass(frozen=True)
class MarkdownChunker:
    max_chars: int = 2400
    profile: str = "md-heading-2400-v1"

    def __post_init__(self) -> None:
        if self.max_chars < 256:
            raise ValueError("max_chars must be >= 256")
        if not self.profile.strip():
            raise ValueError("chunk profile is required")

    def split(self, raw: str, *, fallback_title: str = "document") -> tuple[MarkdownChunk, ...]:
        if not raw.strip():
            raise ValueError("cannot chunk empty document")
        lines = raw.splitlines()
        title = next(
            (line.lstrip("# ").strip() for line in lines if line.startswith("#")),
            fallback_title,
        )
        heading = title
        units: list[tuple[str, str]] = []
        for block in (part.strip() for part in raw.split("\n\n")):
            if not block:
                continue
            first = block.splitlines()[0]
            if first.startswith("#"):
                heading = first.lstrip("# ").strip() or title
            labelled = f"Document: {title}\nSection: {heading}\n\n{block}"
            for piece in self._split_large_unit(labelled):
                units.append((heading, piece))

        chunks: list[MarkdownChunk] = []
        buffer: list[tuple[str, str]] = []

        def flush(items: list[tuple[str, str]]) -> None:
            if not items:
                return
            chunks.append(MarkdownChunk(
                ordinal=len(chunks),
                section=items[-1][0],
                text="\n\n".join(item[1] for item in items).strip(),
            ))

        for unit in units:
            candidate = "\n\n".join([item[1] for item in buffer] + [unit[1]])
            if buffer and len(candidate) > self.max_chars:
                previous = (
                    buffer[-1]
                    if len(buffer[-1][1]) <= self.max_chars // 4
                    else None
                )
                flush(buffer)
                buffer = ([previous] if previous else []) + [unit]
            else:
                buffer.append(unit)
        flush(buffer)

        if not chunks:
            raise ValueError("chunker produced no chunks")
        return tuple(chunks)

    def _split_large_unit(self, text: str) -> tuple[str, ...]:
        if len(text) <= self.max_chars:
            return (text,)
        pieces: list[str] = []
        buffer: list[str] = []
        for line in text.splitlines():
            candidate = "\n".join(buffer + [line])
            if buffer and len(candidate) > self.max_chars:
                pieces.append("\n".join(buffer).strip())
                buffer = [line]
            elif len(line) > self.max_chars:
                if buffer:
                    pieces.append("\n".join(buffer).strip())
                    buffer = []
                for start in range(0, len(line), self.max_chars):
                    piece = line[start:start + self.max_chars].strip()
                    if piece:
                        pieces.append(piece)
            else:
                buffer.append(line)
        if buffer:
            pieces.append("\n".join(buffer).strip())
        return tuple(piece for piece in pieces if piece)
