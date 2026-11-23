"""Read local Wi-Fi credentials without exposing them in errors or repr()."""
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import stat

from .protocol import WifiError, Network, profile_xml

MAX_CONFIG_BYTES = 8192


@dataclass(frozen=True)
class WifiConfig:
    ssid: str
    password: str = field(repr=False)


def _unique_fields(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise WifiError("Il file di configurazione contiene campi duplicati.")
        result[key] = value
    return result


def load_config(path):
    """Load an owner-only regular JSON file, with a bounded size.

    Validate before opening any printer connection. Never include JSON content,
    property names from malformed input, or parser excerpts in errors.
    """
    try:
        # NONBLOCK prevents accidentally blocking on a pipe/device passed as a
        # filename. fstat checks the same descriptor that will actually be read.
        fd = os.open(Path(path).expanduser(), os.O_RDONLY | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise WifiError("La configurazione deve essere un normale file JSON.")
            if info.st_mode & 0o077:
                raise WifiError("Il file contiene credenziali: limita i permessi con chmod 600 sul file di configurazione.")
            if info.st_size > MAX_CONFIG_BYTES:
                raise WifiError("File di configurazione troppo grande (massimo 8 KiB).")
            raw = stream.read(MAX_CONFIG_BYTES + 1)
    except OSError:
        raise WifiError("Impossibile leggere il file di configurazione; controlla percorso e permessi.") from None
    if len(raw) > MAX_CONFIG_BYTES:
        raise WifiError("File di configurazione troppo grande (massimo 8 KiB).")
    try:
        values = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_fields)
    except (UnicodeError, ValueError, RecursionError):
        raise WifiError("File di configurazione non valido: serve JSON UTF-8 con ssid e password.") from None
    if not isinstance(values, dict) or set(values) != {"ssid", "password"}:
        raise WifiError("Il file JSON deve contenere esattamente i campi ssid e password.")
    if not isinstance(values["ssid"], str) or not isinstance(values["password"], str):
        raise WifiError("I campi ssid e password devono essere stringhe JSON.")
    try:
        # Empty password means an open network; actual advertised security is
        # checked after discovery, before sending any credentials.
        profile_xml(Network(values["ssid"], "infrastructure", "wpa" if values["password"] else "none"),
                    values["password"])
    except UnicodeError:
        raise WifiError("SSID o password contengono caratteri non validi.") from None
    return WifiConfig(values["ssid"], values["password"])
