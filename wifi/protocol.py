"""LEDM Wi-Fi sequence from HP HPLIP's base/LedmWifi.py.

Never log request bodies or raw profile replies: these can contain credentials.
"""
from dataclasses import dataclass
import ipaddress
import re
import time
import xml.etree.ElementTree as ET

IO = "http://www.hp.com/schemas/imaging/con/ledm/iomgmt/2008/11/30"
DD = "http://www.hp.com/schemas/imaging/con/dictionaries/1.0/"
WIFI = "http://www.hp.com/schemas/imaging/con/wifi/2009/06/26"
for prefix, namespace in (("io", IO), ("dd", DD), ("wifi", WIFI)):
    ET.register_namespace(prefix, namespace)


class WifiError(Exception):
    pass


def local(tag):
    return tag.rsplit("}", 1)[-1]


def text(element, name, default=""):
    return next((node.text or default for node in element.iter() if local(node.tag) == name), default)


def parse(body):
    if b"<!DOCTYPE" in body.upper() or b"<!ENTITY" in body.upper():
        raise WifiError("Risposta XML non supportata.")
    try:
        return ET.fromstring(body)
    except ET.ParseError:
        raise WifiError("La stampante ha restituito XML non valido.") from None


def decode_ssid(value):
    try:
        return bytes.fromhex(value).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        raise WifiError("SSID restituito dalla stampante non decodificabile come UTF-8.") from None


@dataclass(frozen=True)
class Network:
    ssid: str
    mode: str
    encryption: str
    channel: str = ""
    signal: str = ""


def profile_xml(network, password):
    ssid = network.ssid.encode("utf-8")
    if not 1 <= len(ssid) <= 32:
        raise WifiError("Il nome della rete deve occupare da 1 a 32 byte UTF-8.")
    security = network.encryption.lower()
    if security != "none" and security not in ("wpa", "wpa2", "wpawpa2", "wpa_psk", "wpa2_psk", "wpa_wpa2_psk"):
        raise WifiError("Questo script gestisce reti WPA/WPA2 personali oppure aperte.")
    if network.mode.lower() != "infrastructure":
        raise WifiError("Selezionare una rete Wi-Fi con router (infrastructure).")
    if security != "none":
        # HPLIP's WpaPassPhraseInfo is a passphrase, not a raw 64-digit PSK.
        if not 8 <= len(password) <= 63 or any(ord(c) < 32 or ord(c) > 126 for c in password):
            raise WifiError("La password WPA deve contenere da 8 a 63 caratteri ASCII stampabili.")
    root = ET.Element(f"{{{IO}}}Profile")
    adapter = ET.SubElement(root, f"{{{IO}}}AdapterProfile")
    wifi = ET.SubElement(adapter, f"{{{IO}}}WifiProfile")
    for name, value in (("SSID", ssid.hex()), ("CommunicationMode", network.mode),
                        ("EncryptionType", network.encryption),
                        ("AuthenticationMode", "open" if security == "none" else network.encryption)):
        ET.SubElement(wifi, f"{{{WIFI}}}{name}").text = value
    if security != "none":
        key = ET.SubElement(wifi, f"{{{IO}}}KeyInfo")
        info = ET.SubElement(key, f"{{{IO}}}WpaPassPhraseInfo")
        for name, value in (("RsnEncryption", "AESOrTKIP"), ("RsnAuthorization", "autoWPA"),
                            ("PassPhrase", password.encode("utf-8").hex())):
            ET.SubElement(info, f"{{{WIFI}}}{name}").text = value
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def power_xml(wrapped=True):
    adapter = ET.Element(f"{{{IO}}}Adapter")
    config = ET.SubElement(adapter, f"{{{IO}}}HardwareConfig")
    ET.SubElement(config, f"{{{DD}}}Power").text = "on"
    if wrapped:
        root = ET.Element(f"{{{IO}}}Adapters")
        root.append(adapter)
    else:
        root = adapter
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def usable_ipv4(value):
    try:
        ip = ipaddress.IPv4Address(value)
        return not (ip.is_unspecified or ip.is_loopback or ip.is_link_local or ip.is_multicast or int(ip) == 0xFFFFFFFF)
    except ipaddress.AddressValueError:
        return False


class WifiDevice:
    def __init__(self, transport):
        self.transport = transport
        self.name = ""
        self.base = ""

    def get(self, path):
        code, body = self.transport.request("GET", path)
        if code != 200:
            raise WifiError(f"Lettura della configurazione Wi-Fi fallita (HTTP {code}).")
        return parse(body)

    def discover(self):
        root = self.get("/IoMgmt/Adapters")
        adapters = [node for node in root.iter() if local(node.tag) == "Adapter"
                    and text(node, "DeviceConnectivityPortType").lower() in ("wifiembedded", "wifiaccessory")]
        if len(adapters) != 1:
            raise WifiError("Impossibile identificare in modo univoco la radio Wi-Fi della J610.")
        self.name = text(adapters[0], "Name")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", self.name):
            raise WifiError("Nome della radio Wi-Fi non supportato.")
        self.base = "/IoMgmt/Adapters/" + self.name
        self._adapter = adapters[0]
        return self.name

    def power_on(self):
        self.discover()
        if text(self._adapter, "Power").lower() == "on":
            return
        # Retry only the documented alternative XML shape after a definitive
        # payload rejection, never after a timeout/ambiguous transmission.
        code, _ = self.transport.request("PUT", self.base, power_xml(), timeout=60)
        if code in (400, 415, 422):
            code, _ = self.transport.request("PUT", self.base, power_xml(False), timeout=60)
        if code not in (200, 204):
            raise WifiError(f"Attivazione della radio Wi-Fi fallita (HTTP {code}).")

    def networks(self, timeout=60):
        if not self.base:
            self.discover()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            code, body = self.transport.request("GET", self.base + "/WifiNetworks", timeout=15)
            if code == 202:
                time.sleep(1)
                continue
            if code != 200:
                raise WifiError(f"Ricerca reti fallita (HTTP {code}); la radio potrebbe essere spenta.")
            networks, seen = [], set()
            for node in parse(body).iter():
                if local(node.tag) != "WifiNetwork":
                    continue
                encoded = text(node, "SSID")
                if not encoded:
                    continue
                try:
                    ssid = decode_ssid(encoded)
                except WifiError:
                    continue
                mode, encryption = text(node, "CommunicationMode"), text(node, "EncryptionType")
                key = (ssid, mode, encryption)
                if key in seen:
                    continue
                seen.add(key)
                networks.append(Network(ssid, mode, encryption, text(node, "Channel"), text(node, "SignalStrength")))
            return sorted(networks, key=lambda net: net.ssid.casefold())
        raise WifiError("La ricerca delle reti non si è conclusa entro il tempo previsto.")

    def status(self):
        # On the J610, GET /Adapters/Wifi0 returns 405. Its live state is
        # returned by the collection, alongside the associated WifiNetwork.
        self.discover()
        adapter = self._adapter
        profile = self.get(self.base + "/Profiles/Active")
        encoded = text(profile, "SSID")
        configured_ssid = decode_ssid(encoded) if encoded else ""
        associated = text(adapter, "SSID")
        ssid = decode_ssid(associated) if associated else ""
        connected = text(adapter, "IsConnected").lower() in ("true", "1")
        addresses = []
        # Scope IPv4 addresses to the Wi-Fi adapter; do not use another
        # interface's IP from a global configuration response.
        for root in (profile,):
            for node in root.iter():
                if local(node.tag) in ("IPAddr", "IPAddress", "IPv4Address") and node.text and usable_ipv4(node.text.strip()):
                    addresses.append(node.text.strip())
        try:
            protocols = self.get(self.base + "/Protocols")
        except WifiError:
            protocols = None
        if protocols is not None:
            for node in protocols.iter():
                if local(node.tag) in ("IPAddr", "IPAddress", "IPv4Address") and node.text and usable_ipv4(node.text.strip()):
                    addresses.append(node.text.strip())
        return {"adapter": self.name, "power": text(adapter, "Power", "unknown"),
                "connected": connected, "ssid": ssid, "configured_ssid": configured_ssid,
                "ipv4": list(dict.fromkeys(addresses))}

    def associate(self, network, password):
        if not self.base:
            self.discover()
        payload = profile_xml(network, password)
        code, _ = self.transport.request("PUT", self.base + "/Profiles/Active", payload, timeout=60)
        if code not in (200, 204):
            raise WifiError(f"La stampante non ha accettato il profilo Wi-Fi (HTTP {code}).")

    def wait_connected(self, ssid, timeout=120):
        deadline = time.monotonic() + timeout
        last = None
        while time.monotonic() < deadline:
            try:
                last = self.status()
            except (WifiError, OSError, RuntimeError):
                # Only reads are retried while the adapter reconnects. A PUT
                # with an ambiguous result is never repeated automatically.
                time.sleep(3)
                continue
            if last["connected"] and last["ssid"] == ssid and last["ipv4"] and last["power"].lower() == "on":
                return last
            time.sleep(3)
        raise WifiError("Profilo inviato, ma connessione e indirizzo IP non confermati. "
                        "Controllare password, rete a 2,4 GHz e WPA/WPA2; poi usare --status.")
