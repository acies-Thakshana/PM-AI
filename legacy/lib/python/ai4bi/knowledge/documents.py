"""Business knowledge taken from documents stored next to a domain package.

Files: storage/semantic/domains/<domain>/documents/*.md or *.txt.
Each paragraph becomes one ``document`` node in the knowledge graph.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ai4bi.knowledge.graph import KnowledgeGraph
from ai4bi.utils.text import slug

DOCUMENT_SUFFIXES = (".md", ".txt")
MIN_PARAGRAPH = 20


def read_paragraphs(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    heading = ""
    out: list[dict[str, Any]] = []
    for block in re.split(r"\n\s*\n", text):
        chunk = block.strip()
        if not chunk:
            continue
        if chunk.startswith("#"):
            first, _, rest = chunk.partition("\n")
            heading = first.lstrip("#").strip()
            chunk = rest.strip()
            if not chunk:
                continue
        flat = re.sub(r"\s+", " ", chunk)
        if len(flat) >= MIN_PARAGRAPH:
            out.append({"heading": heading, "text": flat})
    return out


def ingest_documents(graph: KnowledgeGraph, folder: Path) -> int:
    """Add or refresh document nodes. Returns the number of paragraphs stored."""
    if not folder.is_dir():
        return 0
    count = 0
    for path in sorted(folder.iterdir()):
        if path.suffix.lower() not in DOCUMENT_SUFFIXES or not path.is_file():
            continue
        doc_id = f"doc.{slug(path.stem)}"
        graph.upsert_node(doc_id, "document", path.name, source=str(path.name))
        for index, paragraph in enumerate(read_paragraphs(path), start=1):
            node_id = f"{doc_id}.{index}"
            graph.upsert_node(
                node_id,
                "document_fact",
                paragraph["text"][:240],
                text=paragraph["text"],
                heading=paragraph["heading"],
                source=path.name,
            )
            graph.add_edge(doc_id, "contains", node_id)
            count += 1
    return count
