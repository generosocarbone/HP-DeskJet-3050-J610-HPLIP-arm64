#!/usr/bin/env python3
"""Scan one J610 flatbed page to PDF, PNG or PNM with the local LEDM frontend."""
import argparse
from datetime import datetime
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent


def convert(pnm, destination, dpi):
    """Convert with macOS ImageIO, preserving the scanner's physical resolution."""
    if destination.suffix.lower() == ".pnm":
        data = pnm.read_bytes()
    else:
        with tempfile.TemporaryDirectory(prefix="j610-convert-") as temporary:
            converted = Path(temporary) / destination.name
            subprocess.run(["/usr/bin/sips", "-s", "dpiWidth", str(dpi),
                            "-s", "dpiHeight", str(dpi), "-s", "format",
                            destination.suffix[1:].lower(), str(pnm), "--out", str(converted)],
                           check=True, stdout=subprocess.DEVNULL)
            data = converted.read_bytes()
    # Exclusive create also protects against a filename collision during scanning.
    with destination.open("xb") as output:
        output.write(data)
    destination.chmod(0o600)


def main():
    parser = argparse.ArgumentParser(description="Acquisisce un foglio dalla HP DeskJet 3050 J610 via USB.")
    parser.add_argument("output", nargs="?", help="File PDF, PNG o PNM nuovo; predefinito: scans/data-ora.pdf")
    args = parser.parse_args()
    destination = Path(args.output).expanduser().resolve() if args.output else ROOT / "scans" / (datetime.now().strftime("%Y-%m-%d_%H-%M-%S") + ".pdf")
    if destination.suffix.lower() not in (".pdf", ".png", ".pnm"):
        raise SystemExit("Specificare un file .pdf, .png o .pnm.")
    if destination.exists():
        raise SystemExit(f"Il file esiste già: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    executable = ROOT / "dist-scanner" / "j610-scanner-probe"
    if not executable.is_file():
        raise SystemExit("Compilare prima con bash scripts/build-scanner.sh")
    serial = None
    for queue in ("HP_Deskjet_3050_J610_native", "HP_Deskjet_3050_J610_series"):
        result = subprocess.run(["/usr/bin/lpstat", "-v", queue], capture_output=True, text=True)
        match = re.search(r"usb://HP/Deskjet%203050%20J610%20series\?serial=([^&\s]+)", result.stdout)
        if result.returncode == 0 and match:
            serial = match[1]
            break
    if not serial:
        raise SystemExit("Coda USB della J610 non trovata o CUPS non accessibile.")
    uri = "/usb/Deskjet_3050_J610_series?serial=" + serial
    print("Scansione in corso: lascia il foglio sul vetro e il coperchio chiuso.", flush=True)
    with tempfile.TemporaryDirectory(prefix="j610-scan-") as temporary:
        pnm = Path(temporary) / "page.pnm"
        result = subprocess.run([str(executable), "--scan", uri, str(pnm)],
                                capture_output=True, text=True, timeout=240)
        if result.returncode:
            raise SystemExit(result.stderr.strip() or "Scansione non riuscita.")
        match = re.search(r"at requested (\d+) dpi", result.stderr)
        if not match:
            raise SystemExit("Scansione acquisita, ma risoluzione non riconosciuta.")
        dpi = int(match[1])
        convert(pnm, destination, dpi)
    print(f"Salvato a {dpi} dpi: {destination}")


if __name__ == "__main__":
    try:
        main()
    except (OSError, subprocess.SubprocessError) as error:
        sys.exit(f"Errore: {error}")
