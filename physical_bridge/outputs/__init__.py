"""Output plugins.  Importing this package registers the built-in types."""
from .base import OUTPUT_TYPES, Output, register_output
from . import osc_out, serial_out, virtual  # noqa: F401  (register plugins)


def create_output(name: str, cfg: dict) -> Output:
    cls = OUTPUT_TYPES[cfg["type"]]
    return cls(name, cfg)


__all__ = ["OUTPUT_TYPES", "Output", "register_output", "create_output"]
