# adfu-tool

Recovery and diagnostics for cheap Actions Semiconductor devices (video
greeting cards, MP4/MP5 players, game consoles) that expose the vendor
**ADFU download mode** over USB (`VID_10D6:PID_10D6`).

It uploads a tiny read-only program into the chip's SRAM, executes it, and
receives memory contents back over USB — recovering the **mask BootROM** and
other memory windows from a device that has no other debug interface.

```
$ adfu-tool devices
MODE    BUS:DEV   PORT PATH    SERIAL
normal  003:012   3          -
$ adfu-tool enter-adfu --drive D
mode switch sent; card is in ADFU mode on port 3
$ adfu-tool dump-rom -o rom.bin
GetInfo OK
loader executing; CPU identity matched
streaming 2048 chunks ...
  chunk 2048/2048

ROM window saved to rom.bin (32768 bytes)
SHA-256 6a69f70faf5e34889cc493f404f87cb249522b758f17a38d9bbd2d1b1e4ec9d5
two passes matched, 5.4s total
```

## What it does

| Command | Purpose |
|---|---|
| `devices` | list Actions devices in normal (mass-storage) and ADFU mode |
| `enter-adfu --drive D` | switch a normal-mode card into ADFU (Windows) |
| `info` | read the ADFU bootROM identity (`CADFUDP` stamp) |
| `dump-rom -o rom.bin` | upload the bundled reader, dump the 32 KiB mask BootROM at `BFC00000`, two-pass verified |
| `dump-rom --window 0xBFC10000:512 --allow-experimental-window` | dump another 64 KiB-aligned window (up to 32 KiB per pass) |
| `upload --file loader.bin --execute --yes` | advanced: run your own loader image |

Every dump is read **twice** and the two passes must match byte-for-byte; the
loader also carries SRAM guard words that must survive the read, and each
frame is sequence/address/length checked. A file is only written after all of
that passes.

## Safety model — read this before using flash tooling expectations

* **Read-only.** adfu-tool sends no flash program/erase commands and the
  bundled loader performs no stores outside its own scratch bytes. There is
  deliberately **no `flash`/`erase` command** in v1.0: no write path has been
  verified on real hardware, and shipping guessed NAND program/erase
  sequences would brick community devices. The transport (`upload --execute`)
  can run any future loader — a verified NAND reader/writer loader can be
  added later without changing this tool.
* **Nothing is retried.** Any unexpected byte, bad status, short write or
  timeout aborts immediately. The device recovers by the vendor's normal
  path: unplug, power off (cover switch / power button), power on.
* **Volatile.** The loader lives in SRAM only; nothing persists across a
  power cycle.
* Your media (SD content) is not touched, but keep backups anyway. A dump
  cannot harm the device; a *crashed* device recovers by power cycle — every
  device this was tested on did.

## Supported hardware

Proven end-to-end on an Actions Semiconductor **V100** (MIPS32 24KEc) card:
identity `10d6:10d6` in ADFU, bootROM stamp `CADFUDP v09 F`, CPU PRId
`00019655`. Other Actions-family chips sharing this ADFU generation may work;
the tool checks the bootROM identity and warns before continuing off-reference
(`--identity-force` skips the check). Windows is required for `enter-adfu`;
the ADFU-mode commands work wherever libusb does.

If the card shows up in ADFU mode with no driver, install a WinUSB driver for
`USB\VID_10D6&PID_10D6` (e.g. Zadig) — the vendor's own `AdfuWinUSB.inf` is
another source.

## Install

**Single-file exe (Windows):** download `adfu-tool.exe` from the release page
— no Python needed.

**From source (any OS):**

```bash
pip install .
adfu-tool --help
```

Requires Python 3.10+, `pyusb`, and a libusb 1.0 backend
(`libusb-package` is used automatically on Windows).

## How the protocol works (summary)

The ADFU interface speaks a BOT-flavoured protocol: a 31-byte CBW
(`USBC` + zero tag + LE32 length + flags + 16-byte CDB) on bulk OUT 0x01,
optional data in 512-byte calls, and a 13-byte CSW (`USBS` + tag/residue/
status, all zero on success) on bulk IN 0x82.

| Stage | CDB | Notes |
|---|---|---|
| GetInfo | `CC` | returns 18-byte stamp `00 "CADFUDP" 09 'F'` |
| RAM upload | `05` addr len | payload is the **whole-image vendor codec** (256-byte XOR table + 12-byte permutation) — never re-encoded per packet |
| Execute | `10` addr | device replies with a 64-byte CPU record, then data frames |

The bundled 2 KiB MIPS32-LE reader (`loader_source/prefix.S`) is uploaded to
`B4061000`, disables interrupts (one CP0 Status write, eight-NOP spacing),
and streams 80-byte frames: `identity32 + LE32 seq/guard/address/length +
32 data bytes`. It reads its window twice; pass 2 must equal pass 1.

A transfer journal (`*.transfers.jsonl`) and a machine-readable report
(`*.report.json`) are written next to the output file.

## Building from source

```bash
pip install pyinstaller
py -3.12 build_exe.py        # produces dist/adfu-tool.exe
py -3.12 -m unittest discover -s tests
```

## Rebuilding the loader for other windows

`loader_source/BUILDING.md` describes the reproducible GNU `mips32-elf`
build (the same one used to produce the bundled image, including the
two-independent-builds and native-codec cross-checks). For simple window
changes you do not need the toolchain: `dump-rom --window` patches the four
immediate-only words in the sealed image and refuses if the surrounding
skeleton does not match.

## Roadmap

* NAND reader loader (page + OOB, hardware ECC reconstruction) — design work,
  separate review, will ship as a loader image + new subcommands.
* NAND program/erase only after a verified write path exists on sacrificial
  hardware. Not before. See the safety model above.
* macOS/Linux `enter-adfu` helpers.

## Provenance and license

The protocol was recovered by analyzing vendor production tools and proven
live on real hardware (an Actions V100 card, 2026-11-04): two complete,
matching 32 KiB passes over the mask BootROM, with the device recovering
normally afterwards. The bundled loader image is the exact artifact that ran
on that hardware; its SHA-256s are pinned in `adfu_tool/data/`.

The image codec is derived from `meta/actions/encrypt.c` in the
[gipi/teardown](https://github.com/gipi/teardown) repository, attributed to
Amaury Pouly / Rockbox — licensed **GPL-2.0-or-later**, and so is this tool.
