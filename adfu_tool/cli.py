"""adfu-tool command line interface."""
import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from . import __version__, device as device_mod, loader as loader_mod
from .codec import encode
from .protocol import (DEFAULT_OVERALL_TIMEOUT_S, GETINFO_IDENTITY, AdfuError,
                       Session)
from .reader import run_read
from .transition import enter_adfu


def _print_devices():
    rows = []
    for mode, found in (("ADFU", device_mod.find_adfu()), ("normal", device_mod.find_normal())):
        for dev in found:
            info = device_mod.describe(dev)
            rows.append((mode, info))
    if not rows:
        print("no Actions devices found (VID 10d6)")
        return 0
    print(f"{'MODE':7} {'BUS:DEV':9} {'PORT PATH':12} SERIAL")
    for mode, info in rows:
        print(f"{mode:7} {info['bus']:03}:{info['address']:03}   "
              f"{'.'.join(map(str, info['port_numbers'])):12} {info['serial'] or '-'}")
    print("\nTo reach ADFU mode from the normal drive:  adfu-tool enter-adfu --drive D")
    return 0


def _parse_window(text: str) -> loader_mod.Window:
    try:
        start_text, count_text = text.split(":")
        return loader_mod.Window(int(start_text, 0), int(count_text, 0))
    except ValueError as error:
        raise AdfuError("window format is START:CHUNKS, e.g. 0xBFC00000:1024") from error


def _open_journal(path: Path):
    journal = path.open("x", encoding="utf-8", newline="\n")

    def record(kind, value):
        journal.write(json.dumps({"utc": datetime.now(timezone.utc).isoformat(),
                                  "monotonic": time.monotonic(),
                                  "kind": kind, "value": value}) + "\n")
        journal.flush()
    return journal, record


def _dump_rom(args):
    window = _parse_window(args.window) if args.window else loader_mod.DEFAULT_WINDOW
    if window != loader_mod.DEFAULT_WINDOW and not args.allow_experimental_window:
        raise AdfuError(
            "non-default windows are experimental (unproven addresses on your "
            "device) - pass --allow-experimental-window to accept this")
    loader_mod.validate_window(window)
    output = Path(args.output)
    if output.exists() and not args.force:
        raise AdfuError(f"{output} exists - pass --force to overwrite")
    if args.raw_loader:
        image_plain = Path(args.raw_loader).read_bytes()
        image_encoded = image_plain if args.raw else encode(image_plain)
    else:
        image_plain, image_encoded = loader_mod.image_for_window(window)

    usb_device = device_mod.open_single_adfu()
    journal = None
    record = lambda kind, value: None
    if not args.no_journal:
        journal, record = _open_journal(output.with_suffix(output.suffix + ".transfers.jsonl"))
    try:
        session = Session(usb_device, record=record)
        identity = session.getinfo(
            expected=None if args.identity_force else GETINFO_IDENTITY)
        started = time.monotonic()
        last = {"n": 0}

        def progress(kind, sequence, total, **extra):
            if kind == "cpu":
                print(f"loader executing; CPU identity {'matched' if extra['cpu']['matches_reference_v100'] else 'DIFFERS from reference'}")
                print(f"streaming {total} chunks ...")
            else:
                last["n"] = sequence
                if sequence % max(1, total // 10) == 0 or sequence == total:
                    print(f"  chunk {sequence}/{total}")

        rom, info = run_read(session, image_encoded, window, on_progress=progress)
        elapsed = time.monotonic() - started
    finally:
        if journal is not None:
            journal.close()

    output.write_bytes(rom)
    report = {
        "tool_version": __version__,
        "utc": datetime.now(timezone.utc).isoformat(),
        "device": device_mod.describe(usb_device.device),
        "identity_hex": identity.hex(),
        "window": info["window"],
        "cpu": info["cpu"],
        "ordering": info["ordering"],
        "passes_match": info["passes_match"],
        "loader": {"plaintext_sha256": loader_mod.sha256(image_plain),
                   "encoded_sha256": loader_mod.sha256(image_encoded),
                   "sealed_default": not args.raw_loader and window == loader_mod.DEFAULT_WINDOW},
        "rom_sha256": loader_mod.sha256(rom),
        "rom_bytes": len(rom),
        "elapsed_seconds": round(elapsed, 3),
        "chunks_received": info["chunks_received"],
    }
    output.with_suffix(output.suffix + ".report.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"\nROM window saved to {output} ({len(rom)} bytes)")
    print(f"SHA-256 {report['rom_sha256']}")
    print(f"two passes matched, {report['elapsed_seconds']}s total")
    return 0


def _upload(args):
    data = Path(args.file).read_bytes()
    if args.raw:
        encoded = data
    else:
        encoded = encode(data)
    if not args.yes:
        raise AdfuError("uploading custom code runs on your device's CPU - "
                        "review the image, then pass --yes")
    usb_device = device_mod.open_single_adfu()
    session = Session(usb_device)
    identity = session.getinfo(
        expected=None if args.identity_force else GETINFO_IDENTITY)
    session.upload(encoded, address=args.address)
    print(f"uploaded {len(encoded)} bytes to {args.address:#010x}")
    if args.execute:
        session.execute(entry=args.address)
        print(f"execute requested at {args.address:#010x}; the loader now owns "
              "the bulk IN pipe - power-cycle to recover")
    return 0


def _info(_args):
    usb_device = device_mod.open_single_adfu()
    session = Session(usb_device)
    identity = session.getinfo()
    print(f"GetInfo identity: {identity.hex()}")
    print(f"ascii stamp:      {identity[1:9].decode('ascii', 'replace')} "
          f"version {identity[9]:02x} '{chr(identity[10])}'")
    return 0


def _enter_adfu(args):
    result = enter_adfu(args.drive, wait_seconds=args.wait)
    print(f"mode switch sent ({result['mode_switch']}); card is in ADFU mode on "
          f"port {'.'.join(map(str, result['adfu_port_numbers'])) or '?'}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="adfu-tool",
        description="Recovery and diagnostics for Actions Semiconductor ADFU "
                    "bootROM devices (read-only; proven on the V100 family).")
    parser.add_argument("--version", action="version", version=f"adfu-tool {__version__}")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("devices", help="list Actions devices in normal and ADFU mode")
    p = sub.add_parser("enter-adfu", help="switch a normal-mode card into ADFU (Windows)")
    p.add_argument("--drive", required=True, help="drive letter of the card, e.g. D")
    p.add_argument("--wait", type=int, default=30)
    p = sub.add_parser("info", help="read the ADFU GetInfo identity")
    p = sub.add_parser("dump-rom", help="upload the reader loader and dump a ROM window")
    p.add_argument("-o", "--output", default="rom.bin")
    p.add_argument("--window", help="experimental START:CHUNKS, e.g. 0xBFC00000:1024")
    p.add_argument("--allow-experimental-window", action="store_true")
    p.add_argument("--raw-loader", help="use a custom 2 KiB loader image instead")
    p.add_argument("--raw", action="store_true", help="with --raw-loader: image is already encoded")
    p.add_argument("--identity-force", action="store_true")
    p.add_argument("--no-journal", action="store_true")
    p.add_argument("--force", action="store_true")
    p = sub.add_parser("gui", help="launch the production-tool style graphical interface")
    p.add_argument("--smoke", action="store_true", help="open, settle, exit (self-test)")
    p = sub.add_parser("upload", help="advanced: upload (and optionally execute) a loader image")
    p.add_argument("--file", required=True)
    p.add_argument("--address", type=lambda s: int(s, 0), default=0xB4061000)
    p.add_argument("--execute", action="store_true")
    p.add_argument("--raw", action="store_true")
    p.add_argument("--identity-force", action="store_true")
    p.add_argument("--yes", action="store_true")
    args = parser.parse_args(argv)

    try:
        if args.command == "devices":
            return _print_devices()
        if args.command == "enter-adfu":
            return _enter_adfu(args)
        if args.command == "info":
            return _info(args)
        if args.command == "dump-rom":
            return _dump_rom(args)
        if args.command == "gui":
            from .gui import run
            return run(smoke=args.smoke)
        if args.command == "upload":
            return _upload(args)
        parser.print_help()
        return 0
    except AdfuError as error:
        print(f"error: {error}", file=sys.stderr)
        print("the device recovers with a unplug -> power off -> power on cycle",
              file=sys.stderr)
        return 2
    except (OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
