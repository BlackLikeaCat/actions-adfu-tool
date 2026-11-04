"""Framing and session tests against fake endpoints."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from adfu_tool.protocol import (GETINFO_CBW, GETINFO_IDENTITY, SUCCESS_CSW,
                                AdfuError, Session, build_cbw, parse_csw,
                                read_execute_response)
from helpers import FakeDevice, HEADER, csw, cpu_response

UPLOAD_2048 = build_cbw(0x05, 0xB4061000, 2048)
EXECUTE = build_cbw(0x10, 0xB4061000, 0)


class PacketTests(unittest.TestCase):
    def test_reference_packet_fixtures(self):
        # Byte-identical to the packets proven live on 2026-11-04.
        self.assertEqual(
            UPLOAD_2048.hex(),
            "55534243000000000008000000001005001006b40008000000000000000000")
        self.assertEqual(
            EXECUTE.hex(),
            "55534243000000000000000000001010001006b40000000000000000000000")
        self.assertEqual(
            build_cbw(0x05, 0xB4060000, 2048).hex(),
            "55534243000000000008000000001005000006b40008000000000000000000")
        self.assertEqual(
            GETINFO_CBW.hex(),
            "555342430000000012000000800010cc000000000000120000000000000000")

    def test_address_and_length_fields(self):
        packet = build_cbw(0x05, 0xB4061800, 4096)
        self.assertEqual(int.from_bytes(packet[16:20], "little"), 0xB4061800)
        self.assertEqual(int.from_bytes(packet[20:24], "little"), 4096)
        self.assertEqual(packet[8:12], (4096).to_bytes(4, "little"))
        self.assertEqual(packet[14], 16)
        self.assertEqual(packet[15], 0x05)


class CswTests(unittest.TestCase):
    def test_success(self):
        self.assertEqual(parse_csw(SUCCESS_CSW), (0, 0, 0))

    def test_rejections(self):
        for bad in (csw(tag=1), csw(residue=1), csw(status=1), csw(status=2),
                    b"", b"USBS", SUCCESS_CSW + b"x", b"xxxx" + bytes(9)):
            with self.subTest(bad=bad), self.assertRaises(AdfuError):
                parse_csw(bad)


class SessionTests(unittest.TestCase):
    def session(self, device):
        return Session(device, clock=iter(range(1000)).__next__)

    def test_getinfo_success(self):
        device = FakeDevice([GETINFO_IDENTITY, csw()])
        identity = Session(device).getinfo()
        self.assertEqual(identity, GETINFO_IDENTITY)
        self.assertEqual(device.writes, [GETINFO_CBW])

    def test_getinfo_partial_delivery(self):
        for split in (1, 9, 17):
            device = FakeDevice([GETINFO_IDENTITY[:split], GETINFO_IDENTITY[split:], csw()])
            self.assertEqual(Session(device).getinfo(), GETINFO_IDENTITY)

    def test_getinfo_identity_mismatch_aborts(self):
        device = FakeDevice([bytes(17) + b"\x01", csw()])
        with self.assertRaises(AdfuError):
            Session(device).getinfo()
        self.assertEqual(len(device.writes), 1)

    def test_upload_splits_and_success_csw(self):
        image = bytes(range(256)) * 8  # 2048
        device = FakeDevice([csw()])
        Session(device).upload(image)
        self.assertEqual(device.writes[0], UPLOAD_2048)
        self.assertEqual(device.writes[1:], [image[n:n + 512] for n in range(0, 2048, 512)])
        self.assertEqual(device.calls, ["out"] * 5 + ["in"])

    def test_upload_bad_status_aborts_without_retry(self):
        for reply in (csw(tag=1), csw(status=2), b"", SUCCESS_CSW + b"x"):
            device = FakeDevice([reply])
            with self.subTest(reply=reply), self.assertRaises(AdfuError):
                Session(device).upload(bytes(2048))
            self.assertEqual(len(device.writes), 5)

    def test_short_out_is_never_resent(self):
        for at in range(1, 6):
            device = FakeDevice([csw()], short_at=at)
            with self.subTest(at=at), self.assertRaises(AdfuError):
                Session(device).upload(bytes(2048))
            self.assertEqual(len(device.calls), at)

    def test_disconnect_is_never_retried(self):
        for at in range(1, 7):
            device = FakeDevice([csw()], fail_at=at)
            with self.subTest(at=at), self.assertRaises(TimeoutError):
                Session(device).upload(bytes(2048))
            self.assertEqual(len(device.calls), at)

    def test_size_limits(self):
        for bad in (bytes(0), bytes(256), bytes(511), bytes(65600)):
            with self.subTest(size=len(bad)), self.assertRaises(AdfuError):
                Session(FakeDevice([])).upload(bad)

    def test_overall_deadline(self):
        now = [0]

        def clock():
            now[0] += 3
            return now[0]

        device = FakeDevice([csw()])
        with self.assertRaisesRegex(AdfuError, "deadline"):
            Session(device, clock=clock, overall_timeout=10).upload(bytes(2048))
        self.assertLess(len(device.writes), 5)

    def test_journal_records_every_transfer(self):
        events = []
        device = FakeDevice([GETINFO_IDENTITY, csw()])
        Session(device, record=lambda k, v: events.append(k)).getinfo()
        self.assertEqual(events, ["out_attempt", "out_complete", "in_attempt",
                                  "in_complete", "in_attempt", "in_complete"])


class ExecuteResponseTests(unittest.TestCase):
    def test_response_only(self):
        device = FakeDevice([cpu_response()])
        data, ordering = read_execute_response(Session(device), HEADER, 64)
        self.assertEqual(ordering, "response_only")
        self.assertEqual(data, cpu_response())

    def test_success_csw_then_response(self):
        reply = csw() + cpu_response()
        for split in (1, 13, 21, 45, 76):
            device = FakeDevice([reply[:split], reply[split:]])
            data, ordering = read_execute_response(Session(device), HEADER, 64)
            with self.subTest(split=split):
                self.assertEqual(ordering, "success_csw_then_response")
                self.assertEqual(data, cpu_response())

    def test_bad_csw_is_rejected(self):
        reply = csw(tag=1) + cpu_response()
        device = FakeDevice([reply])
        with self.assertRaises(AdfuError):
            read_execute_response(Session(device), HEADER, 64)

    def test_wrong_identity_is_rejected(self):
        device = FakeDevice([b"V100XXXX" + bytes(24) + bytes(32)])
        with self.assertRaises(AdfuError):
            read_execute_response(Session(device), HEADER, 64)


if __name__ == "__main__":
    unittest.main()
