"""adfu-tool: recovery and diagnostics for Actions Semiconductor ADFU devices.

The wire protocol implemented here is the one proven live on an Actions V100
card (2026-11-03/04): BOT-style CBW/CSW framing over the vendor WinUSB
interface (VID_10D6 & PID_10D6), opcode 0x05 RAM upload with whole-image
vendor codec, opcode 0x10 execute, and the 80-byte frame stream emitted by
the uploaded reader program. Read-only by design: nothing here writes or
erases flash.
"""
__version__ = "1.0.0"
