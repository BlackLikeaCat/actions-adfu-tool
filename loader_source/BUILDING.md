# Rebuilding the reader loader from source

The bundled image (`adfu_tool/data/rom32k_h9.bin`, `rom32k_h9.encoded.bin`)
was produced by a reproducible build. This recipe recreates it byte-for-byte
and explains how to build a loader for a different window when the runtime
patching in `adfu-tool dump-rom --window` is not enough.

## Prerequisites

* Any MIPS32 big-endian-capable binutils configured for **little-endian
  MIPS32** (`mips32-elf-as`, `ld`, `objcopy`, `nm`, `objdump`). The original
  build used GNU binutils 2.42 from Ubuntu's `binutils-mipsel-linux-gnu`
  cross package (package SHA-256
  `678275fa6abda0b7fabbc55ff6a09654701a6c2e86794c7a0b6e773e663e49db`).
* Python 3 with the memory-book repo available for `tools/build_v100_greeting.py`
  (toolchain invocation helpers) and `tools/decode_adfu_adec.py` (codec).

## The image contract

* Exactly **2048 bytes**, loaded and entered at **B4061000**
  (image `[B4061000,B4061800)`), uploaded via opcode `05`, executed via
  opcode `10` at the same address.
* Entry word at offset 0 is `b start` (PC-relative); code lives at
  `+0x400`; the last word may be `code_end`.
* The response identity32 (32 bytes: `"V100R901"` + 8 build-id + 16 cookie)
  is emitted as `lui/ori/sw` triples from `identity.inc`, which `build.py`
  generates from the recipe hash and a 16-byte random cookie.
* Scratch: 40 bytes at `[B40617C0,B40617E8)` — two guard words plus a
  32-byte pattern, re-verified around every chunk load.
* Response protocol: one 64-byte CPU record, then `2 x chunks_per_pass`
  80-byte frames (`identity32 + LE32 seq/guard/address/length + 32 bytes`).
* Window constants live in four immediate-only words (two `lui $a1`,
  one `ori $t6, total`, one `ori $t6, per_pass`) — this is what
  `adfu-tool`'s runtime patcher edits.

## Reproducible rebuild of the bundled image

```bash
py -3.12 loader/experimental_rom32k/build.py --output-dir NEW_DIR
# with the same 16-byte cookie (build/rom32k-h9/reviewed/cookie.hex) the
# rebuild is byte-identical to the released image
```

The build performs two clean compilations and requires them to match, then
cross-checks the encoded image against an independently compiled native
codec, and round-trips the vendor codec in Python.

## Changing the window

For a new window `[start, start + 32*chunks_per_pass)`:

1. `start` must be **64 KiB aligned** (the code initializes the pointer with
   `lui` only) and `chunks_per_pass <= 1024` (the stream is capped at 2048
   frames over two passes).
2. Edit `prefix.S`: the two `lui $a1, 0xbfc0` sites (initial and pass-reset),
   `ori $t6, $zero, 1024` (chunks per pass) and `ori $t6, $zero, 2048`
   (total frames = 2 x chunks_per_pass).
3. Rebuild, verify with `objdump`, and encode with the codec
   (`tools/decode_adfu_adec.py: transform(data, key_table(), decode=False)`).
4. Alternatively run it without a toolchain:
   `adfu-tool dump-rom --window START:CHUNKS --allow-experimental-window`
   patches the sealed image at runtime and refuses if the skeleton changed.

## Verification expectations

Any loader change is a new payload running on your CPU. At minimum:

* disassemble the full 2 KiB and confirm only the intended immediates moved;
* keep the store set exactly: 2 guard words + 32 pattern bytes + the
  B0290088/B0290014/B0290015/B0290017 USB FIFO writes;
* keep both poll loops bounded (0x00100000 iterations);
* test the host side against fake endpoints (see `tests/`).
