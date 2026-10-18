# -*- coding: utf-8 -*-
"""AI4BI dataset catalog (Dataiku Python recipe).

Inputs:  the fact datasets of the domain.
Outputs: one dataset with a row per column: role, description, profile, restricted flag.
"""

import json

import ai4bi_dataiku  # noqa: F401  registers the LLM Mesh client
from ai4bi_dataiku.recipes import run_metadata_recipe

print(json.dumps(run_metadata_recipe(), indent=2, default=str))
