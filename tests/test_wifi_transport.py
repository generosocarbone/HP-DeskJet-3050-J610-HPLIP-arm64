"""Exercise HTTP framing and failure handling without loading native USB code."""
import contextlib
import ctypes
import io
import unittest
from unittest.mock import patch

from wifi.transport import IO_TIMEOUT, MAX_BODY, TransportError, UsbTransport, normalize_uri


URI = "hp:/usb/Deskjet_3050_J610_series?serial=offline"
PATH = "/IoMgmt/Adapters/Wifi0/Profiles/Active"
SECRET = b"not-a-real-password"


class FakeNativeUsb:
    """The ctypes ABI boundary, with fragmented reads and short writes."""

    def __init__(self, response, fragment=3, end_result=0, fail_first_channel=False,
                 write_result=0):
        self.response = response
        self.fragment = fragment
        self.end_result = end_result
        self.fail_first_channel = fail_first_channel
        self.write_result = write_result
        self.sent = bytearray()
        self.services = []
        self.write_calls = 0
        self.channels_closed = 0
        self.devices_closed = 0

    def hpmud_open_device(self, uri, mode, handle):
        handle._obj.value = 1
        return 0

    def hpmud_close_device(self, device):
        self.devices_closed += 1
        return 0

    def hpmud_open_channel(self, device, service, handle):
        self.services.append(service)
        handle._obj.value = 2
        return 12 if self.fail_first_channel and len(self.services) == 1 else 0

    def hpmud_close_channel(self, device, channel):
        self.channels_closed += 1
        return 0

    def hpmud_write_channel(self, device, channel, buffer, size, timeout, written):
        count = min(7, size)
        self.sent.extend(ctypes.string_at(buffer, count))
        written._obj.value = count
        self.write_calls += 1
        return self.write_result

    def hpmud_read_channel(self, device, channel, buffer, size, timeout, received):
        count = min(size, self.fragment, len(self.response))
        ctypes.memmove(buffer, self.response, count)
        self.response = self.response[count:]
        received._obj.value = count
        return 0 if count else self.end_result


class WifiTransportTests(unittest.TestCase):
    def request(self, response, **options):
        native = FakeNativeUsb(response, **options)
        with patch("wifi.transport.load_library", return_value=native):
            transport = UsbTransport(URI)
        # No native library, USB device or CUPS command is used by these tests.
        with transport:
            result = transport.request("PUT", PATH, SECRET)
        self.assertEqual(native.channels_closed, 1)
        self.assertEqual(native.devices_closed, 1)
        self.assertGreater(native.write_calls, 1)
        self.assertTrue(native.sent.endswith(SECRET))
        self.assertEqual(native.sent.count(SECRET), 1)
        self.assertIn(f"Content-Length: {len(SECRET)}\r\n".encode(), native.sent)
        return result

    def assert_rejected(self, response, **options):
        native = FakeNativeUsb(response, **options)
        with patch("wifi.transport.load_library", return_value=native):
            transport = UsbTransport(URI)
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            with self.assertRaises(TransportError) as error:
                with transport:
                    transport.request("PUT", PATH, SECRET)
        self.assertNotIn(SECRET.decode(), str(error.exception))
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue(), "")
        self.assertEqual(native.channels_closed, 1)
        self.assertEqual(native.devices_closed, 1)
        return native

    def test_fragmented_content_length_and_partial_writes(self):
        response = b"HTTP/1.1 200 OK\r\nContent-Length: 6\r\n\r\n<xml/>"
        self.assertEqual(self.request(response), (200, b"<xml/>"))

    def test_chunked_fragments_extensions_and_trailers(self):
        response = (b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n"
                    b"3\r\n<xm\r\n3;extension=x\r\nl/>\r\n0\r\nX-Test: yes\r\n\r\n")
        self.assertEqual(self.request(response), (200, b"<xml/>"))

    def test_no_content_response(self):
        response = b"HTTP/1.1 204 No Content\r\nContent-Length: 0\r\n\r\n"
        self.assertEqual(self.request(response), (204, b""))

    def test_truncated_fixed_length_response(self):
        self.assert_rejected(b"HTTP/1.1 200 OK\r\nContent-Length: 9\r\n\r\n<xml/>")

    def test_truncated_chunked_response(self):
        self.assert_rejected(b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n9\r\n<xml/>")

    def test_usb_timeout_does_not_accept_incomplete_body(self):
        response = b"HTTP/1.1 200 OK\r\nContent-Length: 6\r\n\r\n"
        self.assert_rejected(response, end_result=IO_TIMEOUT)

    def test_malformed_response_does_not_expose_secret(self):
        self.assert_rejected(SECRET + b"\r\n")

    def test_declared_body_above_limit_is_rejected(self):
        response = f"HTTP/1.1 200 OK\r\nContent-Length: {MAX_BODY + 1}\r\n\r\n".encode()
        self.assert_rejected(response)

    def test_failed_partial_put_is_not_retried(self):
        native = self.assert_rejected(b"", fail_first_channel=True, write_result=12)
        # Fallback is allowed before transmission, never after a partial PUT.
        self.assertEqual(native.services, [b"HP-LEDM-SCAN", b"HP-EWS-LEDM"])
        self.assertEqual(native.write_calls, 1)

    def test_uri_must_identify_the_exact_usb_model(self):
        self.assertEqual(normalize_uri("/usb/Deskjet_3050_J610_series?serial=offline"), URI)
        for invalid in ("hp:/net/Deskjet_3050_J610_series?ip=192.168.1.23",
                        "hp:/usb/Deskjet_3050A_J611_series?serial=offline",
                        URI + "\r\nInjected"):
            with self.subTest(uri=invalid):
                with self.assertRaises(TransportError):
                    normalize_uri(invalid)


if __name__ == "__main__":
    unittest.main()
