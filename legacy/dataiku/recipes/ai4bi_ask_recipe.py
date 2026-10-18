# -*- coding: utf-8 -*-
"""AI4BI question recipe (Dataiku Python recipe).

Inputs:  one or more fact datasets, one question dataset (column input_question,
         optional Expected_SQL_Query), optional previous knowledge_graph dataset.
Outputs: a results dataset and a dataset named knowledge_graph.
Project variables: AIBI_DOMAIN, AIBI_LLM_CONNECTION (see dataiku/project_variables.example.json).
"""

import json

import ai4bi_dataiku  # noqa: F401  registers the LLM Mesh client
from ai4bi_dataiku.recipes import run_ask_recipe

print(json.dumps(run_ask_recipe(), indent=2, default=str))
