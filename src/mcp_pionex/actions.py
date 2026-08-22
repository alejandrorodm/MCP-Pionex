"""
Registry of executors for two-phase actions.

``prepare_*`` tools validate parameters and store them under a token
(safety.prepare_action). ``confirm_action`` looks the token up and dispatches
to the executor registered for the stored action name — the model never gets
to pass execution parameters at confirm time.
"""

EXECUTORS: dict = {}


def executor(action_name: str):
    def wrap(fn):
        EXECUTORS[action_name] = fn
        return fn
    return wrap
