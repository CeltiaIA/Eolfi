"""Observación de caja negra: sesiones reproducibles, comparación entre ejecuciones y repetición desde guion."""
from eolfi.observe.compare import compare_sessions, run_compare, run_replay
from eolfi.observe.script import ScriptError, validate_script
from eolfi.observe.session import execute, load_session, run_observation

__all__ = ["ScriptError", "compare_sessions", "execute", "load_session", "run_compare", "run_observation",
           "run_replay", "validate_script"]
