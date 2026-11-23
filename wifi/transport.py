"""Bounded HTTP-over-USB transport for the HP DeskJet 3050 J610.

Uses HPLIP's native USB implementation. Does not print or persist request or
response bodies, which may contain Wi-Fi credentials. Constructing the class
loads the library; device access starts on __enter__ or the first request.
"""
from __future__ import annotations

import ctypes
import http.client
import io
import math
from pathlib import Path
import re
import subprocess
import time
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parent.parent
MAX_BODY = 2 * 1024 * 1024
MAX_REQUEST = 128 * 1024
MAX_WIRE = MAX_BODY + 128 * 1024
IO_TIMEOUT = 49


class TransportError(RuntimeError):
    """A sanitized transport failure, without printer payloads or secrets."""


def discover_uri() -> str:
    """Use the existing exact-model CUPS queues; ignore unrelated printers."""
    for queue in ("HP_Deskjet_3050_J610_native", "HP_Deskjet_3050_J610_series"):
        try:
            result = subprocess.run(["/usr/bin/lpstat", "-v", queue], capture_output=True,
                                    text=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            continue
        match = re.search(r"usb://HP/Deskjet%203050%20J610%20series\?serial=([^&\s]+)", result.stdout)
        if result.returncode == 0 and match:
            return normalize_uri("hp:/usb/Deskjet_3050_J610_series?serial=" + unquote(match[1]))
    raise TransportError("Coda USB della J610 non trovata o CUPS non accessibile.")


def normalize_uri(uri: str) -> str:
    if uri.startswith("/usb/"):
        uri = "hp:" + uri
    if not re.fullmatch(r"hp:/usb/Deskjet_3050_J610_series\?serial=[A-Za-z0-9_.-]{1,128}", uri):
        raise TransportError("È richiesto l'URI USB del modello DeskJet 3050 J610.")
    return uri


def load_library(path: Path | None = None):
    path = path or ROOT / "dist-wifi/libhpmud-j610.dylib"
    if not path.is_file():
        raise TransportError("Compilare prima con bash scripts/build-wifi.sh.")
    try:
        lib = ctypes.CDLL(str(path))
    except OSError:
        raise TransportError("Impossibile caricare il trasporto USB; ricompilare e verificare libusb.") from None
    integer = ctypes.c_int
    out_integer = ctypes.POINTER(integer)
    signatures = {
        "hpmud_open_device": [ctypes.c_char_p, integer, out_integer],
        "hpmud_close_device": [integer],
        "hpmud_open_channel": [integer, ctypes.c_char_p, out_integer],
        "hpmud_close_channel": [integer, integer],
        "hpmud_write_channel": [integer, integer, ctypes.c_void_p, integer, integer, out_integer],
        "hpmud_read_channel": [integer, integer, ctypes.c_void_p, integer, integer, out_integer],
    }
    for name, signature in signatures.items():
        function = getattr(lib, name)
        function.argtypes = signature
        function.restype = integer
    return lib


class _ChannelReader(io.RawIOBase):
    def __init__(self, transport, channel, deadline):
        self.transport, self.channel, self.deadline = transport, channel, deadline
        self.total = 0

    def readable(self):
        return True

    def readinto(self, target):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise TransportError("Tempo massimo della risposta USB superato.")
        size = min(len(target), 32768)
        if size == 0:
            return 0
        buffer = ctypes.create_string_buffer(size)
        count = ctypes.c_int()
        result = self.transport.lib.hpmud_read_channel(
            self.transport.device, self.channel, buffer, size, max(1, math.ceil(remaining)),
            ctypes.byref(count))
        if count.value < 0 or count.value > size:
            raise TransportError("Lunghezza della risposta USB non valida.")
        if result not in (0, IO_TIMEOUT):
            raise TransportError(f"Lettura USB non riuscita (codice {result}).")
        if count.value:
            self.total += count.value
            if self.total > MAX_WIRE:
                raise TransportError("Risposta della stampante troppo grande.")
            target[:count.value] = buffer.raw[:count.value]
            return count.value
        # USB has no socket-style EOF. A timeout ends an unframed HTTP body;
        # HTTPResponse still rejects truncated Content-Length/chunked messages.
        return 0


class _ChannelSocket:
    def __init__(self, reader):
        self.reader = reader

    def makefile(self, mode):
        return io.BufferedReader(self.reader, buffer_size=8192)


class UsbTransport:
    def __init__(self, uri: str | None = None):
        self.uri = normalize_uri(uri) if uri else None
        self.lib = load_library()
        self.device = None

    def __enter__(self):
        if self.device is None:
            if self.uri is None:
                self.uri = discover_uri()
            handle = ctypes.c_int()
            result = self.lib.hpmud_open_device(self.uri.encode("ascii"), 1, ctypes.byref(handle))
            if result:
                raise TransportError(f"Apertura USB non riuscita (codice {result}); controllare collegamento e accesso USB.")
            self.device = handle.value
        return self

    def close(self):
        if self.device is not None:
            handle, self.device = self.device, None
            self.lib.hpmud_close_device(handle)

    def __exit__(self, exc_type, exc, traceback):
        self.close()

    def _open_channel(self):
        for service in (b"HP-LEDM-SCAN", b"HP-EWS-LEDM"):
            handle = ctypes.c_int()
            result = self.lib.hpmud_open_channel(self.device, service, ctypes.byref(handle))
            if result == 0:
                return handle.value
        raise TransportError(f"Canale di configurazione USB non disponibile (codice {result}).")

    def request(self, method: str, path: str, body: bytes = b"", timeout: int = 30):
        method = method.upper()
        if method not in ("GET", "PUT"):
            raise TransportError("Metodo HTTP non supportato.")
        if not (path.startswith("/IoMgmt/") or path == "/IoMgmt/Adapters" or path == "/DevMgmt/IOConfigDyn.xml"):
            raise TransportError("Risorsa di configurazione non consentita.")
        if any(ord(character) <= 32 or ord(character) >= 127 for character in path):
            raise TransportError("Percorso HTTP non valido.")
        if not isinstance(body, bytes) or len(body) > MAX_REQUEST or not 1 <= timeout <= 120:
            raise TransportError("Dimensione richiesta o timeout non valido.")
        if method == "GET" and body:
            raise TransportError("Una richiesta GET non deve contenere un corpo.")
        self.__enter__()
        channel = self._open_channel()
        response = None
        deadline = time.monotonic() + timeout
        try:
            header = (f"{method} {path} HTTP/1.1\r\nHost: localhost\r\n"
                      "User-Agent: hplip-j610-macos\r\nContent-Type: text/xml; charset=utf-8\r\n"
                      f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n").encode("ascii")
            data = header + body
            offset = 0
            while offset < len(data):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TransportError("Tempo massimo dell'invio USB superato; esito della scrittura incerto.")
                block = data[offset:offset + 32768]
                buffer = ctypes.create_string_buffer(block, len(block))
                written = ctypes.c_int()
                result = self.lib.hpmud_write_channel(self.device, channel, buffer, len(block),
                                                      max(1, math.ceil(remaining)), ctypes.byref(written))
                if result or not 0 < written.value <= len(block):
                    raise TransportError(f"Invio USB non riuscito (codice {result}); esito della scrittura incerto.")
                offset += written.value
            response = http.client.HTTPResponse(_ChannelSocket(_ChannelReader(self, channel, deadline)))
            response.begin()
            if response.length is not None and response.length > MAX_BODY:
                raise TransportError("Risposta della stampante troppo grande.")
            body_result = response.read(MAX_BODY + 1)
            if len(body_result) > MAX_BODY:
                raise TransportError("Risposta della stampante troppo grande.")
            # read(amt) may return a short fixed-length body without raising.
            if response.length not in (None, 0):
                raise TransportError("Risposta HTTP incompleta.")
            return response.status, body_result
        except (http.client.HTTPException, OSError, ValueError):
            raise TransportError("Risposta HTTP USB non valida o incompleta; nessun tentativo automatico ripetuto.") from None
        finally:
            if response is not None:
                response.close()
            self.lib.hpmud_close_channel(self.device, channel)
