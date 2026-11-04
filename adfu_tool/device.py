"""pyusb discovery and endpoint validation for Actions ADFU devices."""
import usb.core

from .protocol import PID_ADFU, PID_NORMAL, VID, AdfuError, BULK_IN, BULK_OUT


def _backend():
    """Prefer the packaged libusb backend (Windows); fall back to the default."""
    try:
        import libusb_package
        return libusb_package.get_libusb1_backend()
    except Exception:
        return None


def _find(pid: int):
    devices = list(usb.core.find(find_all=True, idVendor=VID, idProduct=pid,
                                 backend=_backend()))
    return sorted(devices, key=lambda d: (d.bus, d.address))


def find_adfu():
    """All devices currently in ADFU download mode."""
    return _find(PID_ADFU)


def find_normal():
    """All devices in normal UDISK mass-storage mode."""
    return _find(PID_NORMAL)


def describe(device) -> dict:
    return {
        "vid_pid": f"{device.idVendor:04x}:{device.idProduct:04x}",
        "bus": device.bus,
        "address": device.address,
        "port_numbers": list(device.port_numbers or []),
        "serial": _safe(lambda: device.serial_number),
        "manufacturer": _safe(lambda: device.manufacturer),
        "product": _safe(lambda: device.product),
        "bcd_device": _safe(lambda: f"{device.bcdDevice:04x}"),
    }


def _safe(call):
    try:
        return call()
    except Exception:
        return None


def check_device(device) -> dict:
    """Validate the ADFU interface layout before any command is sent.

    Required: one vendor-class interface with bulk OUT 0x01 and bulk IN 0x82
    (512 bytes). Deviations from the reference card (bcdDevice 0100, EP0 64)
    are reported but not fatal - other Actions family models differ.
    """
    info = describe(device)
    try:
        device.set_configuration()
    except usb.core.USBError as error:
        if "Configuration" not in str(error) and "BUSY" not in str(error).upper():
            raise AdfuError(f"cannot configure ADFU device: {error}") from error
    config = device.get_active_configuration()
    interfaces = [i for i in config if i.bInterfaceClass == 0xFF]
    if len(interfaces) != 1:
        raise AdfuError(f"expected one vendor-class interface, found {len(interfaces)}")
    endpoints = {ep.bEndpointAddress: ep for ep in interfaces[0]}
    out_ep, in_ep = endpoints.get(BULK_OUT), endpoints.get(BULK_IN)
    if out_ep is None or in_ep is None:
        raise AdfuError("ADFU interface lacks bulk OUT 0x01 / IN 0x82")
    if (out_ep.bmAttributes & 3) != 2 or (in_ep.bmAttributes & 3) != 2:
        raise AdfuError("ADFU endpoints are not bulk")
    if in_ep.wMaxPacketSize != 512:
        raise AdfuError(f"bulk IN max packet is {in_ep.wMaxPacketSize}, expected 512")
    info["bcd_device_reference"] = info["bcd_device"] == "0100"
    return info


class UsbDevice:
    """Adapter giving a pyusb device the write/read surface Session expects."""

    def __init__(self, device):
        self.device = device

    def write(self, data: bytes, timeout_ms: int) -> int:
        return self.device.write(BULK_OUT, data, timeout=timeout_ms)

    def read(self, timeout_ms: int) -> bytes:
        return bytes(self.device.read(BULK_IN, 512, timeout=timeout_ms))


def open_single_adfu():
    """Return a checked UsbDevice when exactly one ADFU device is present."""
    devices = find_adfu()
    if len(devices) != 1:
        raise AdfuError(
            f"expected exactly one ADFU device (VID {VID:04x} PID {PID_ADFU:04x}), "
            f"found {len(devices)} - run 'adfu-tool devices' or enter ADFU mode first")
    device = devices[0]
    check_device(device)
    return UsbDevice(device)
