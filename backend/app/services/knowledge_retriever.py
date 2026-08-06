"""
Deterministic retrieval over an unstructured domain-knowledge markdown file.
Chunks by section heading, scores chunks against a query with plain
term-frequency overlap (no ML model, no LLM call) -- this is a lookup problem,
not a reasoning problem, so it stays out of the agent layer.

`KnowledgeBase` is parameterized by file path so the same retrieval logic
serves multiple knowledge bases (Phase 1 produce, Phase 4 chocolate) without
duplicating the algorithm.
"""
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from app.config import CHOCOLATE_KNOWLEDGE_PATH, KNOWLEDGE_PATH

_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "for", "on", "is", "are",
    "this", "that", "with", "as", "by", "at", "from", "be", "it", "its", "than",
    "not", "but", "if", "into", "per", "vs", "each",
}


@dataclass
class Chunk:
    heading: str
    text: str


def _tokenize(text: str):
    words = re.findall(r"[a-zA-Z][a-zA-Z\-]+", text.lower())
    return [w for w in words if w not in _STOPWORDS and len(w) > 2]


def _load_chunks(path: Path) -> list[Chunk]:
    raw = path.read_text(encoding="utf-8")
    sections = re.split(r"\n(?=##+ )", raw)
    chunks = []
    for section in sections:
        section = section.strip()
        if not section:
            continue
        heading_match = re.match(r"##+\s*(.+)", section)
        heading = heading_match.group(1).strip() if heading_match else "Introduction"
        chunks.append(Chunk(heading=heading, text=section))
    return chunks


class KnowledgeBase:
    def __init__(self, path: Path):
        self._chunks = _load_chunks(path)

    def retrieve(self, query: str, top_k: int = 4) -> list[Chunk]:
        """Rank chunks by term-frequency overlap with the query, return top_k."""
        query_terms = Counter(_tokenize(query))
        if not query_terms:
            return self._chunks[:top_k]

        scored = []
        for chunk in self._chunks:
            chunk_terms = Counter(_tokenize(chunk.text))
            score = sum(count * chunk_terms.get(term, 0) for term, count in query_terms.items())
            # small boost for heading matches -- headings signal the chunk's topic directly
            if any(term in chunk.heading.lower() for term in query_terms):
                score += 5
            scored.append((score, chunk))

        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [chunk for score, chunk in scored[:top_k] if score > 0] or self._chunks[:top_k]

    def retrieve_for(self, terms: list[str], extra_terms: str = "", top_k_chunks: int = 6) -> str:
        """Build a query from the given terms, return joined deduplicated chunk text,
        ready to drop into an agent prompt."""
        query = " ".join(terms) + " " + extra_terms
        seen = set()
        parts = []
        for chunk in self.retrieve(query, top_k=top_k_chunks):
            if chunk.heading in seen:
                continue
            seen.add(chunk.heading)
            parts.append(chunk.text)
        return "\n\n".join(parts)


produce_knowledge = KnowledgeBase(KNOWLEDGE_PATH)
chocolate_knowledge = KnowledgeBase(CHOCOLATE_KNOWLEDGE_PATH)
