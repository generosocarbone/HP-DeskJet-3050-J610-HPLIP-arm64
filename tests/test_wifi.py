import contextlib
import io
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from wifi.protocol import Network, WifiDevice, WifiError, profile_xml, text, usable_ipv4


def xml(value):
    return value.encode()


class FakeTransport:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def request(self, method, path, body=b"", timeout=30):
        self.calls.append((method, path, body))
        result = next(self.responses)
        if isinstance(result, Exception):
            raise result
        return result


ADAPTERS = xml('''<Adapters><Adapter><HardwareConfig><Name>Wifi0</Name>
<DeviceConnectivityPortType>wifiEmbedded</DeviceConnectivityPortType><Power>on</Power>
</HardwareConfig><WifiNetwork><SSID>4f6c64</SSID><IsConnected>false</IsConnected>
</WifiNetwork></Adapter><Adapter><HardwareConfig><Name>usb0</Name>
<DeviceConnectivityPortType>usb</DeviceConnectivityPortType></HardwareConfig></Adapter></Adapters>''')


class WifiProtocolTests(unittest.TestCase):
    def test_utf8_hex_payload_and_xml_escaping(self):
        network = Network('Caffè & <Casa>', 'Infrastructure', 'WPA')
        password = 'Example&<Secret>42'
        payload = profile_xml(network, password)
        root = ET.fromstring(payload)
        self.assertEqual(bytes.fromhex(text(root, 'SSID')).decode(), network.ssid)
        self.assertEqual(bytes.fromhex(text(root, 'PassPhrase')).decode(), password)
        self.assertEqual(text(root, 'AuthenticationMode'), 'WPA')
        self.assertEqual(text(root, 'RsnAuthorization'), 'autoWPA')
        self.assertNotIn(password.encode(), payload)

    def test_open_network_has_no_key(self):
        root = ET.fromstring(profile_xml(Network('Guest', 'infrastructure', 'none'), ''))
        self.assertEqual(text(root, 'AuthenticationMode'), 'open')
        self.assertEqual(text(root, 'PassPhrase'), '')

    def test_real_j610_wpa_psk_token_is_preserved(self):
        root = ET.fromstring(profile_xml(Network('Example', 'Infrastructure', 'WPA_PSK'), 'example123'))
        self.assertEqual(text(root, 'EncryptionType'), 'WPA_PSK')
        self.assertEqual(text(root, 'AuthenticationMode'), 'WPA_PSK')

    def test_validation_before_transport(self):
        for network, password in [
            (Network('x' * 33, 'infrastructure', 'wpa'), 'example123'),
            (Network('x', 'infrastructure', 'wpa3'), 'example123'),
            (Network('x', 'adhoc', 'wpa'), 'example123'),
            (Network('x', 'infrastructure', 'wpa'), 'short'),
        ]:
            with self.subTest(network=network):
                with self.assertRaises(WifiError) as error:
                    profile_xml(network, password)
                self.assertNotIn(password, str(error.exception))

    def test_live_status_reads_collection_not_put_only_endpoint(self):
        profile = xml('<Profile><SSID>4e6577</SSID></Profile>')
        protocols = xml('<Protocols><IPv4Address><IPv4Address>192.168.1.23</IPv4Address></IPv4Address></Protocols>')
        transport = FakeTransport([(200, ADAPTERS), (200, profile), (200, protocols)])
        result = WifiDevice(transport).status()
        self.assertFalse(result['connected'])
        self.assertEqual(result['configured_ssid'], 'New')
        self.assertEqual(result['ssid'], 'Old')
        self.assertEqual(result['ipv4'], ['192.168.1.23'])
        self.assertTrue(all(method == 'GET' for method, _, _ in transport.calls))
        self.assertNotIn('/IoMgmt/Adapters/Wifi0', [path for _, path, _ in transport.calls])

    def test_stale_address_does_not_report_success(self):
        device = WifiDevice(None)
        stale = dict(connected=False, ssid='New', configured_ssid='New', power='on', ipv4=['192.168.1.23'])
        with patch.object(device, 'status', return_value=stale), patch('wifi.protocol.time.sleep'), \
             patch('wifi.protocol.time.monotonic', side_effect=[0, 1, 2, 11]):
            with self.assertRaises(WifiError):
                device.wait_connected('New', timeout=10)

    def test_connection_retries_transient_reads(self):
        device = WifiDevice(None)
        ready = dict(connected=True, ssid='New', power='on', ipv4=['192.168.1.23'])
        with patch.object(device, 'status', side_effect=[WifiError('HTTP 503'), ready]), \
             patch('wifi.protocol.time.sleep'):
            self.assertEqual(device.wait_connected('New'), ready)

    def test_wifi_search_202_duplicates_and_literal_values(self):
        network = '<WifiNetwork><SSID>43617361</SSID><CommunicationMode>Infrastructure</CommunicationMode><EncryptionType>WPA</EncryptionType><Channel>6</Channel></WifiNetwork>'
        transport = FakeTransport([(200, ADAPTERS), (202, b''), (200, xml('<WifiNetworks>' + network * 2 + '</WifiNetworks>'))])
        with patch('wifi.protocol.time.sleep'):
            nets = WifiDevice(transport).networks()
        self.assertEqual(nets, [Network('Casa', 'Infrastructure', 'WPA', '6', '')])

    def test_failed_credential_put_not_retried_or_logged(self):
        transport = FakeTransport([(200, ADAPTERS), RuntimeError('ambiguous USB write')])
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            with self.assertRaises(RuntimeError):
                WifiDevice(transport).associate(Network('Casa', 'infrastructure', 'wpa'), 'example123')
        self.assertEqual(sum(method == 'PUT' for method, _, _ in transport.calls), 1)
        self.assertEqual(output.getvalue(), '')

    def test_reject_non_routable_addresses(self):
        for address in ('0.0.0.0', '127.0.0.1', '169.254.1.2', '224.0.0.1', '255.255.255.255', 'bad'):
            self.assertFalse(usable_ipv4(address))
        self.assertTrue(usable_ipv4('192.168.1.23'))

    def test_offline_dry_run(self):
        script = Path(__file__).resolve().parent.parent / 'scripts/configure-wifi.py'
        result = subprocess.run(['python3', str(script), '--dry-run'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Nessun accesso USB', result.stdout)


if __name__ == '__main__':
    unittest.main()
