"""Dataiku adapter for AI4BI.

This package is the only place that imports ``dataiku``. The import happens
inside functions, so the package itself loads without Dataiku installed.
Importing it registers the ``mesh`` LLM mode with the core library.
"""

from ai4bi.llm.client import register_llm_factory
from ai4bi_dataiku.llm_mesh import DataikuMeshClient, mesh_client_factory, resolve_llm_id

register_llm_factory("mesh", mesh_client_factory)

__all__ = ["DataikuMeshClient", "mesh_client_factory", "resolve_llm_id"]
