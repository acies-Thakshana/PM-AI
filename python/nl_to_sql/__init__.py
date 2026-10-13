"""python.nl_to_sql — bridge stubs to an external NL-to-SQL engine."""

from python.nl_to_sql.bridge import ask, ask_debug, configure_external_engine, run_nlq

__all__ = ["ask", "ask_debug", "configure_external_engine", "run_nlq", "NLQRunner"]


def __getattr__(name: str):
    if name == "NLQRunner":
        from python.nl_to_sql.bridge import NLQRunner

        return NLQRunner
    raise AttributeError(name)
