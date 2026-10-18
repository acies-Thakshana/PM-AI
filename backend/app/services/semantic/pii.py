"""Name-based detection of personal data columns.

A conservative first line of defence for datasets nobody has classified yet: a column whose name
looks personal is treated as restricted, so its values never reach a model prompt, a SQL result
or a catalog sample. A steward's explicit tags in the semantic package always apply on top.
"""

from __future__ import annotations

import re

import pandas as pd

PII_NAME = re.compile(
    r"(^|_|\s)(email|e_mail|phone|mobile|ssn|social_security|passport|contact_email|"
    r"date_of_birth|dob|street_address|ip_address)(_|$|\s)",
    re.I,
)


def inferred_restricted_columns(frames: dict[str, pd.DataFrame]) -> set[str]:
    return {
        str(column)
        for frame in frames.values()
        for column in frame.columns
        if PII_NAME.search(str(column).replace("-", "_"))
    }
