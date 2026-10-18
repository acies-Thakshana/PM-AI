# -*- coding: utf-8 -*-
"""AI4BI execution-accuracy scoring (Dataiku Python recipe).

Inputs:  the results dataset from ai4bi_ask_recipe and the same fact datasets.
Outputs: a detail dataset (one row per question) and, optionally, a dataset whose
         name contains "summary" for accuracy, confusion matrix, latency, and confidence.
"""

import json

import ai4bi_dataiku  # noqa: F401  registers the LLM Mesh client
from ai4bi_dataiku.recipes import run_evaluation_recipe

print(json.dumps(run_evaluation_recipe(), indent=2, default=str))
