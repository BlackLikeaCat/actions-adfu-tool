"""UDISK -> ADFU mode switch (Windows) and ADFU arrival wait.

Proven sequence: send vendor CDB ``CB 21`` to the mass-storage volume, close
the volume handle, then eject the drive. The device detaches and re-enumerates
as VID_10D6 & PID_10D6 within a few seconds. The command usually "hangs" or
errors because the device leaves mid-command - any outcome is treated as sent.

Recovery from any state: unplug, power off (the cover switch), power on.
"""
import ctypes
import platform
import subprocess
import time
from ctypes import wintypes
from pathlib import Path

from .protocol import AdfuError
from . import device as device_mod

IOCTL_SCSI_PASS_THROUGH_DIRECT = 0x0004D014
DATA_IN = 1
GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
SHARE_RW = 1 | 2
OPEN_EXISTING = 3
SENSE_LEN = 32

MODE_SWITCH_CDB = bytes([0xCB, 0x21] + [0] * 8 + [1, 0, 0])


class _SCSI_PTD(ctypes.Structure):
    _fields_ = [
        ("Length", ctypes.c_ushort), ("ScsiStatus", ctypes.c_ubyte),
        ("PathId", ctypes.c_ubyte), ("TargetId", ctypes.c_ubyte),
        ("Lun", ctypes.c_ubyte), ("CdbLength", ctypes.c_ubyte),
        ("SenseInfoLength", ctypes.c_ubyte), ("DataIn", ctypes.c_ubyte),
        ("DataTransferLength", ctypes.c_ulong), ("TimeOutValue", ctypes.c_ulong),
        ("DataBuffer", ctypes.c_void_p), ("SenseInfoOffset", ctypes.c_ulong),
        ("Cdb", ctypes.c_ubyte * 16),
    ]


def _open_volume(letter: str):
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    path = f"\\\\.\\{letter}:"
    handle = k32.CreateFileW(path, GENERIC_READ | GENERIC_WRITE, SHARE_RW, None,
                             OPEN_EXISTING, 0, None)
    if handle in (-1, 0xFFFFFFFFFFFFFFFF):
        error = ctypes.get_last_error()
        if error == 5:
            raise AdfuError(
                f"access denied opening {path} - close programs using the drive "
                "and run from an elevated prompt")
        raise AdfuError(f"cannot open {path}: {ctypes.WinError(error)}")
    return handle


def _send_mode_switch(handle, timeout_s: int = 8) -> str:
    """Send CB 21; the device typically detaches mid-command."""
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    ptd_size = ctypes.sizeof(_SCSI_PTD)
    inbuf = (ctypes.c_ubyte * (ptd_size + SENSE_LEN + 16))()
    ptd = _SCSI_PTD.from_buffer(inbuf)
    ptd.Length = ptd_size
    ptd.CdbLength = len(MODE_SWITCH_CDB)
    ptd.SenseInfoLength = SENSE_LEN
    ptd.DataIn = DATA_IN
    ptd.DataTransferLength = 1
    ptd.TimeOutValue = timeout_s
    ptd.SenseInfoOffset = ptd_size
    data = (ctypes.c_ubyte * 1)()
    ptd.DataBuffer = ctypes.cast(data, ctypes.c_void_p)
    for i, byte in enumerate(MODE_SWITCH_CDB):
        ptd.Cdb[i] = byte
    returned = wintypes.DWORD(0)
    ok = k32.DeviceIoControl(handle, IOCTL_SCSI_PASS_THROUGH_DIRECT,
                             inbuf, len(inbuf), inbuf, len(inbuf),
                             ctypes.byref(returned), None)
    k32.CloseHandle(handle)
    return "completed" if ok else "device_left_mid_command (expected)"


def _win_disk_number(letter: str):
    script = f"(Get-Partition -DriveLetter {letter} -ErrorAction Stop).DiskNumber"
    try:
        proc = subprocess.run(["powershell", "-NoProfile", "-Command", script],
                              capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    out = (proc.stdout or "").strip()
    return out if out.isdigit() else None


def _win_device_instance(disk_number: str):
    script = (f"(Get-CimInstance Win32_DiskDrive -Filter 'Index={disk_number}')"
              ".PNPDeviceID")
    try:
        proc = subprocess.run(["powershell", "-NoProfile", "-Command", script],
                              capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return (proc.stdout or "").strip() or None


def _eject_shell(letter: str) -> None:
    script = ("$sh = New-Object -ComObject Shell.Application; "
              f"$sh.Namespace(17).ParseName('{letter}:\\').InvokeVerb('Eject')")
    subprocess.run(["powershell", "-NoProfile", "-Command", script],
                   capture_output=True, text=True, timeout=30, check=False)
    for _ in range(10):
        if not Path(f"{letter}:/").exists():
            return
        time.sleep(0.5)
    raise AdfuError(f"could not eject {letter}: - use 'Safely Remove Hardware'")


def _eject(letter: str) -> None:
    """Eject via CM_Request_Device_EjectW with the Shell verb as fallback."""
    disk_number = _win_disk_number(letter)
    instance = _win_device_instance(disk_number) if disk_number else None
    if not instance:
        _eject_shell(letter)
        return
    cfgmgr32 = ctypes.WinDLL("cfgmgr32")
    locate = cfgmgr32.CM_Locate_DevNodeW
    eject = cfgmgr32.CM_Request_Device_EjectW
    locate.argtypes = (ctypes.POINTER(ctypes.c_ulong), ctypes.c_wchar_p, ctypes.c_ulong)
    locate.restype = ctypes.c_ulong
    eject.argtypes = (ctypes.c_ulong, ctypes.c_void_p, ctypes.c_void_p,
                      ctypes.c_ulong, ctypes.c_ulong)
    eject.restype = ctypes.c_ulong
    devinst = ctypes.c_ulong(0)
    if locate(ctypes.byref(devinst), instance, 0) != 0:
        _eject_shell(letter)
        return
    if eject(devinst, None, None, 0, 0) != 0:
        # Vetoed handles are common even when idle; the Shell verb usually works.
        _eject_shell(letter)
        return
    for _ in range(10):
        if not Path(f"{letter}:/").exists():
            return
        time.sleep(0.5)


def enter_adfu(drive_letter: str, wait_seconds: int = 30) -> dict:
    """Switch a normal-mode card into ADFU and wait for re-enumeration."""
    if platform.system() != "Windows":
        raise AdfuError("automatic mode switch is Windows-only; send vendor CDB "
                        "CB 21 to the volume and eject it with your OS tools")
    letter = drive_letter.upper().rstrip(":")
    if not Path(f"{letter}:/").exists():
        raise AdfuError(f"no volume {letter}: - connect the card in normal mode")
    handle = _open_volume(letter)
    outcome = _send_mode_switch(handle)
    _eject(letter)
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        found = device_mod.find_adfu()
        if len(found) == 1:
            return {"mode_switch": outcome, "adfu_port_numbers": list(found[0].port_numbers or [])}
        time.sleep(0.5)
    raise AdfuError(f"card did not re-enter ADFU within {wait_seconds}s - "
                    "unplug, power-cycle, and retry once")
