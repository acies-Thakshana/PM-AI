"""LLM-first AI4BI engine with a living knowledge graph.

Onboarding YAML is grounding (schema, registered joins, dictionary, PII).
It is not a rigid compiler. Intent, SQL, metrics, and answers come from the LLM.
After every question the graph is updated with what the model learned.
"""

from aibi.llmkg.engine import ask_with_graph
from aibi.llmkg.graph import KnowledgeGraph

__all__ = ["KnowledgeGraph", "ask_with_graph"]
