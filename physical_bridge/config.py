"""Load and validate the YAML configuration."""
from __future__ import annotations

import copy
import importlib
import importlib.util
import sys
from pathlib import Path
from typing import Any

import yaml

from .frame import KINDS
from .processing.steps import ConfigError

DEFAULTS: dict[str, Any] = {
    "bridge": {"tick_hz": 60, "start_armed": True, "plugins": []},
    "dashboard": {"enabled": True, "host": "127.0.0.1", "port": 8080, "refresh_hz": 15},
    "inputs": {
        "osc": {"enabled": True, "host": "0.0.0.0", "port": 9000},
        "websocket": {"enabled": True, "host": "0.0.0.0", "port": 9001},
        "midi": {"enabled": False, "port": None, "virtual": False, "normalize": True},
    },
    "outputs": {},
    "streams": {},
}


def load_plugins(names: list, base_dir: Path | None = None) -> None:
    """Import user output plugins: a module name (``my_pkg.dmx``) or a path to
    a ``.py`` file, relative to the config file."""
    for name in names or []:
        path = Path(name)
        if base_dir is not None and not path.is_absolute():
            path = base_dir / path
        try:
            if str(name).endswith(".py"):
                spec = importlib.util.spec_from_file_location(f"pb_plugin_{path.stem}", path)
                if spec is None or spec.loader is None or not path.exists():
                    raise FileNotFoundError(path)
                module = importlib.util.module_from_spec(spec)
                sys.modules[spec.name] = module
                spec.loader.exec_module(module)
            else:
                importlib.import_module(name)
        except Exception as exc:  # noqa: BLE001
            raise ConfigError(f"cannot load plugin {name!r}: {exc}") from None


def _merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(path: str | Path) -> dict:
    path = Path(path)
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        raise ConfigError(f"config file not found: {path}") from None
    except yaml.YAMLError as exc:
        raise ConfigError(f"YAML syntax error in {path}: {exc}") from None
    cfg = normalize_config(raw, base_dir=path.parent)
    cfg["_path"] = str(path)
    return cfg


def normalize_config(raw: dict, base_dir: Path | None = None) -> dict:
    if not isinstance(raw, dict):
        raise ConfigError("the config file must contain a mapping at the top level")
    unknown = set(raw) - set(DEFAULTS)
    if unknown:
        raise ConfigError(f"unknown top-level config keys: {', '.join(sorted(unknown))}")
    cfg = _merge(DEFAULTS, raw)
    cfg["outputs"] = cfg.get("outputs") or {}
    cfg["streams"] = cfg.get("streams") or {}

    from .outputs import OUTPUT_TYPES  # registry, includes built-ins
    load_plugins(cfg["bridge"].get("plugins"), base_dir)

    for name, out in cfg["outputs"].items():
        if not isinstance(out, dict):
            raise ConfigError(f"output '{name}' must be a mapping")
        t = out.get("type")
        if t not in OUTPUT_TYPES:
            raise ConfigError(f"output '{name}': type must be one of {tuple(OUTPUT_TYPES)} (got {t!r}); "
                              "custom types need their module listed under bridge.plugins")
        if t in ("serial", "rs485") and not out.get("port"):
            raise ConfigError(f"output '{name}': 'port' is required (e.g. /dev/ttyUSB0, COM3 or auto)")
        if t == "osc" and not out.get("port"):
            raise ConfigError(f"output '{name}': 'port' is required for OSC forwarding")

    for name, st in cfg["streams"].items():
        if not isinstance(st, dict):
            raise ConfigError(f"stream '{name}' must be a mapping")
        kind = st.get("type")
        if kind not in KINDS:
            raise ConfigError(f"stream '{name}': type must be one of {KINDS} (got {kind!r})")
        st.setdefault("source", f"/pb/{name}")
        st.setdefault("pipeline", [])
        st.setdefault("outputs", [])
        if not isinstance(st["pipeline"], list):
            raise ConfigError(f"stream '{name}': pipeline must be a list of steps")
        refs = []
        for ref in st["outputs"]:
            if isinstance(ref, str):
                ref = {"name": ref}
            if not isinstance(ref, dict) or "name" not in ref:
                raise ConfigError(f"stream '{name}': output entries must be a name or {{name: ..., address: ...}}")
            if ref["name"] not in cfg["outputs"]:
                raise ConfigError(f"stream '{name}' sends to unknown output '{ref['name']}'")
            refs.append(ref)
        st["outputs"] = refs
        size = st.get("input_size")
        if size is not None and (not isinstance(size, (list, tuple)) or len(size) != 2):
            raise ConfigError(f"stream '{name}': input_size must be [width, height]")
        rng = st.get("input_range")
        if rng is not None and (not isinstance(rng, (list, tuple)) or len(rng) != 2 or rng[0] == rng[1]):
            raise ConfigError(f"stream '{name}': input_range must be [low, high]")
        if isinstance(st["source"], list) and kind not in ("angles",):
            raise ConfigError(f"stream '{name}': a list of sources is only supported for 'angles' streams")
    return cfg
