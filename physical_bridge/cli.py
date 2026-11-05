"""Command line entry point: ``physical-bridge -c config.yaml``."""
from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys
from pathlib import Path

from . import __version__
from .config import load_config
from .processing.steps import ConfigError


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="physical-bridge",
                                description="Route data from creative software to hardware.")
    p.add_argument("-c", "--config", default="config.yaml", help="YAML config file (default: config.yaml)")
    p.add_argument("--check", action="store_true", help="validate the config and exit")
    p.add_argument("--list-ports", action="store_true", help="list serial ports and MIDI inputs, then exit")
    p.add_argument("--init", metavar="FILE", help="write a starter config file and exit")
    p.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    p.add_argument("--version", action="version", version=f"physical-bridge {__version__}")
    return p


def list_ports() -> None:
    try:
        from .outputs.serial_out import list_serial_ports
        ports = list_serial_ports()
        print("Serial ports:")
        for p in ports or []:
            print(f"  {p['device']:<20} {p['description']}")
        if not ports:
            print("  (none found)")
    except RuntimeError as exc:
        print(f"Serial: {exc}")
    try:
        import mido
        print("MIDI inputs:")
        for name in mido.get_input_names() or ["(none found)"]:
            print(f"  {name}")
    except Exception as exc:  # noqa: BLE001
        print(f"MIDI: unavailable ({exc})")


async def run(cfg: dict) -> None:
    from .bridge import Bridge
    from .dashboard import Dashboard

    bridge = Bridge(cfg)
    await bridge.start()
    dashboard = None
    if cfg["dashboard"].get("enabled", True):
        dashboard = Dashboard(bridge, cfg["dashboard"])
        await dashboard.start()

    print(f"\nPhysical Bridge {__version__} running")
    for inp in bridge.inputs.values():
        state = inp.detail if inp.listening else f"NOT LISTENING - {inp.last_error}"
        print(f"  input   {inp.type_name:<10} {state}")
    for name, out in bridge.outputs.items():
        print(f"  output  {name:<10} ({out.type_name}) {out.detail or ''}")
    print(f"  streams {', '.join(bridge.streams) or '(none)'}")
    if dashboard:
        print(f"\n  Dashboard: {dashboard.url}\n")
    print("Press Ctrl+C to stop.")

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # Windows
            pass
    try:
        await stop.wait()
    finally:
        print("\nStopping...")
        if dashboard:
            await dashboard.stop()
        await bridge.stop()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s", datefmt="%H:%M:%S")
    if args.list_ports:
        list_ports()
        return 0
    if args.init:
        src = Path(__file__).parent / "starter_config.yaml"
        dst = Path(args.init)
        if dst.exists():
            print(f"{dst} already exists, not overwriting")
            return 1
        dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"wrote {dst}")
        return 0
    try:
        cfg = load_config(args.config)
        # building the bridge validates every pipeline step and output
        from .bridge import Bridge
        Bridge(cfg)
    except ConfigError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 2
    if args.check:
        print(f"{args.config}: OK ({len(cfg['streams'])} streams, {len(cfg['outputs'])} outputs)")
        return 0
    try:
        asyncio.run(run(cfg))
    except KeyboardInterrupt:
        pass
    return 0
