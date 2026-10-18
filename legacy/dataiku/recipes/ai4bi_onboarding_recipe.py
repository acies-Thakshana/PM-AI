# -*- coding: utf-8 -*-
"""Dynamic semantic onboarding (Dataiku Python recipe).

Inputs: all fact datasets plus optional prior semantic_registry and knowledge_graph.
Outputs: dataset_catalog, semantic_registry, and optional knowledge_graph/onboarding_audit.
Adding a fact dataset in the Flow requires no Python or YAML changes.
"""

import json

import ai4bi_dataiku  # noqa: F401  registers the LLM Mesh client
from ai4bi_dataiku.recipes import run_onboarding_recipe

print(json.dumps(run_onboarding_recipe(), indent=2, default=str))
