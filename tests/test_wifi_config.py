"""Credential-file validation and noninteractive setup without USB access."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from wifi.config import load_config
from wifi.protocol import Network, WifiError


ROOT = Path(__file__).resolve().parent.parent
PASSWORD = ' Example&"WiFi\\42 '


def load_cli():
    spec = importlib.util.spec_from_file_location("j610_configure_wifi", ROOT / "scripts/configure-wifi.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class WifiConfigTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="j610-config-test-")
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "wifi-config.json"

    def write(self, data=None, raw=None, mode=0o600):
        self.path.write_text(raw if raw is not None else json.dumps(data), encoding="utf-8")
        self.path.chmod(mode)
        return self.path

    def assert_safe_rejection(self, path=None):
        output, errors = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            with self.assertRaises(WifiError) as raised:
                load_config(path or self.path)
        combined = str(raised.exception) + output.getvalue() + errors.getvalue()
        self.assertNotIn(PASSWORD, combined)
        self.assertNotIn(PASSWORD.encode().hex(), combined)

    def test_preserves_unicode_ssid_and_password_exactly(self):
        config = load_config(self.write({"ssid": "Caffè & Casa", "password": PASSWORD}))
        self.assertEqual(config.ssid, "Caffè & Casa")
        self.assertEqual(config.password, PASSWORD)
        self.assertNotIn(PASSWORD, repr(config))

    def test_ssid_limit_is_utf8_bytes(self):
        self.assertEqual(load_config(self.write({"ssid": "é" * 16, "password": PASSWORD})).ssid, "é" * 16)
        for ssid in ("", "a" * 33, "é" * 17):
            with self.subTest(ssid_length=len(ssid)):
                self.write({"ssid": ssid, "password": PASSWORD})
                self.assert_safe_rejection()

    def test_empty_password_allowed_for_open_network(self):
        config = load_config(self.write({"ssid": "Guest", "password": ""}))
        self.assertEqual(config.password, "")

    def test_nonempty_password_requires_supported_wpa_passphrase(self):
        for password in ("short", "a" * 64, "password\n", "caffè-password"):
            with self.subTest(password_length=len(password)):
                self.write({"ssid": "Example", "password": password})
                with self.assertRaises(WifiError) as raised:
                    load_config(self.path)
                self.assertNotIn(password, str(raised.exception))

    def test_malformed_duplicate_and_unknown_fields_are_rejected(self):
        cases = [
            '{"ssid": "Example", "password": "' + PASSWORD,
            '{"ssid":"Example","password":"firstvalue","password":"secondvalue"}',
            json.dumps({"ssid": "Example", "password": PASSWORD, "extra": "value"}),
        ]
        for raw in cases:
            with self.subTest(kind=raw[:12]):
                self.write(raw=raw)
                self.assert_safe_rejection()

    def test_exact_schema_and_string_fields_required(self):
        cases = [None, [], "text", {}, {"ssid": "Example"}, {"password": PASSWORD},
                 {"ssid": 10, "password": PASSWORD}, {"ssid": "Example", "password": None},
                 {"ssid": "Example", "password": False}]
        for data in cases:
            with self.subTest(kind=type(data).__name__):
                self.write(data)
                self.assert_safe_rejection()

    def test_rejects_group_or_other_permissions(self):
        for mode in (0o640, 0o604, 0o620, 0o602, 0o610, 0o601):
            with self.subTest(mode=oct(mode)):
                self.write({"ssid": "Example", "password": PASSWORD}, mode=mode)
                self.assert_safe_rejection()

    def test_nonregular_or_missing_file_is_rejected(self):
        self.assert_safe_rejection(Path(self.temporary.name))
        self.assert_safe_rejection(self.path)

    def test_invalid_unicode_and_oversized_file_rejected_without_values(self):
        self.write(raw='{"ssid":"\\ud800","password":"example123"}')
        self.assert_safe_rejection()
        self.write(raw=' ' * 8193 + json.dumps({"ssid": "Example", "password": PASSWORD}))
        self.assert_safe_rejection()


class WifiConfigCliTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cli = load_cli()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="j610-config-cli-test-")
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "wifi-config.json"
        self.write_config()

    def write_config(self, ssid="Example", password=PASSWORD):
        self.path.write_text(json.dumps({"ssid": ssid, "password": password}), encoding="utf-8")
        self.path.chmod(0o600)

    def run_fake_setup(self, networks):
        device = MagicMock()
        device.networks.return_value = networks
        device.wait_connected.return_value = {"ipv4": ["192.168.1.23"]}
        output, errors = io.StringIO(), io.StringIO()
        with patch("wifi.transport.UsbTransport") as transport, \
             patch.object(self.cli, "WifiDevice", return_value=device), \
             patch.object(self.cli.sys.stdin, "isatty", return_value=False), \
             patch("builtins.input", side_effect=AssertionError("Unexpected interactive prompt")), \
             patch.object(self.cli.getpass, "getpass", side_effect=AssertionError("Unexpected password prompt")), \
             contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            self.cli.main(["--config", str(self.path)])
        transport.assert_called_once()
        self.assertNotIn(PASSWORD, output.getvalue() + errors.getvalue())
        self.assertNotIn(PASSWORD.encode().hex(), output.getvalue() + errors.getvalue())
        return device

    def test_config_selects_exact_network_and_applies_without_tty(self):
        selected = Network("Example", "Infrastructure", "WPA_PSK", "6", "5")
        device = self.run_fake_setup([Network("Other", "Infrastructure", "WPA_PSK"), selected])
        device.associate.assert_called_once_with(selected, PASSWORD)
        device.wait_connected.assert_called_once_with("Example")

    def test_config_open_network_uses_empty_password_without_prompt(self):
        self.write_config(password="")
        selected = Network("Example", "Infrastructure", "none")
        device = self.run_fake_setup([selected])
        device.associate.assert_called_once_with(selected, "")

    def test_dry_run_validates_file_without_usb_or_password_output(self):
        output, errors = io.StringIO(), io.StringIO()
        with patch("wifi.transport.UsbTransport") as transport, \
             patch.object(self.cli.sys.stdin, "isatty", return_value=False), \
             patch("builtins.input", side_effect=AssertionError("Unexpected prompt")), \
             patch.object(self.cli.getpass, "getpass", side_effect=AssertionError("Unexpected prompt")), \
             contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            self.cli.main(["--config", str(self.path), "--dry-run"])
        transport.assert_not_called()
        self.assertNotIn(PASSWORD, output.getvalue() + errors.getvalue())
        self.assertNotIn(PASSWORD.encode().hex(), output.getvalue() + errors.getvalue())

    def test_invalid_file_fails_before_usb(self):
        self.path.write_text('{"password": "' + PASSWORD, encoding="utf-8")
        with patch("wifi.transport.UsbTransport") as transport:
            with self.assertRaises(WifiError):
                self.cli.main(["--config", str(self.path)])
        transport.assert_not_called()

    def test_conflicting_flags_rejected_before_usb(self):
        for extra in (["--ssid", "Example"], ["--status"], ["--list"]):
            with self.subTest(extra=extra), patch("wifi.transport.UsbTransport") as transport, \
                 contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as raised:
                    self.cli.main(["--config", str(self.path), *extra])
                self.assertEqual(raised.exception.code, 2)
            transport.assert_not_called()

    def test_missing_or_ambiguous_network_never_prompts_or_associates(self):
        choices = [[], [Network("Other", "Infrastructure", "WPA_PSK")],
                   [Network("Example", "Infrastructure", "WPA_PSK"), Network("Example", "Infrastructure", "none")]]
        for networks in choices:
            device = MagicMock()
            device.networks.return_value = networks
            with self.subTest(networks=len(networks)), patch("wifi.transport.UsbTransport"), \
                 patch.object(self.cli, "WifiDevice", return_value=device), \
                 patch("builtins.input", side_effect=AssertionError("Unexpected prompt")), \
                 patch.object(self.cli.getpass, "getpass", side_effect=AssertionError("Unexpected prompt")), \
                 contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(WifiError):
                    self.cli.main(["--config", str(self.path)])
            device.associate.assert_not_called()

    def test_password_security_mismatch_never_associates(self):
        for password, security in ((PASSWORD, "none"), ("", "WPA_PSK")):
            self.write_config(password=password)
            device = MagicMock()
            device.networks.return_value = [Network("Example", "Infrastructure", security)]
            with self.subTest(security=security), patch("wifi.transport.UsbTransport"), \
                 patch.object(self.cli, "WifiDevice", return_value=device), \
                 patch("builtins.input", side_effect=AssertionError("Unexpected prompt")), \
                 patch.object(self.cli.getpass, "getpass", side_effect=AssertionError("Unexpected prompt")), \
                 contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(WifiError) as raised:
                    self.cli.main(["--config", str(self.path)])
            device.associate.assert_not_called()
            if password:
                self.assertNotIn(password, str(raised.exception))


if __name__ == "__main__":
    unittest.main()
