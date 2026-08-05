"""
Deterministic retrieval over the unstructured domain-knowledge markdown file.
Chunks by section heading, scores chunks against a query with plain
term-frequency overlap (no ML model, no LLM call) -- this is a lookup problem,
not a reasoning problem, so it stays out of the agent layer.
"""
import re
from collections import Counter
from dataclasses import dataclass

from app.config import KNOWLEDGE_PATH

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


def _load_chunks() -> list[Chunk]:
    raw = KNOWLEDGE_PATH.read_text(encoding="utf-8")
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


_CHUNKS = _load_chunks()


def retrieve(query: str, top_k: int = 4) -> list[Chunk]:
    """Rank chunks by term-frequency overlap with the query, return top_k."""
    query_terms = Counter(_tokenize(query))
    if not query_terms:
        return _CHUNKS[:top_k]

    scored = []
    for chunk in _CHUNKS:
        chunk_terms = Counter(_tokenize(chunk.text))
        score = sum(count * chunk_terms.get(term, 0) for term, count in query_terms.items())
        # small boost for heading matches -- headings signal the chunk's topic directly
        if any(term in chunk.heading.lower() for term in query_terms):
            score += 5
        scored.append((score, chunk))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [chunk for score, chunk in scored[:top_k] if score > 0] or _CHUNKS[:top_k]


def retrieve_for_shipments(commodities: list[str], facility_names: list[str], extra_terms: str = "") -> str:
    """Build a combined query from the shipments under review and return joined chunk text,
    deduplicated, ready to drop into the Agent 1 prompt."""
    query = " ".join(commodities) + " " + " ".join(facility_names) + " " + extra_terms
    seen = set()
    parts = []
    for chunk in retrieve(query, top_k=6):
        if chunk.heading in seen:
            continue
        seen.add(chunk.heading)
        parts.append(chunk.text)
    return "\n\n".join(parts)
