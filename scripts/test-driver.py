#!/usr/bin/env python3
"""Exercise the actual macOS PDF -> raster -> hpcups pipeline, without printing."""
import hashlib
import json
import pathlib
import re
import subprocess

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "build" / "verification"
FILTER = ROOT / "dist" / "filter" / "hpcups"
PPD = ROOT / "dist" / "ppd" / "hp-deskjet_3050_j610_series.ppd"


def create_pdf(path, black_only=False):
    # One A4 page with text, coloured bars and fine lines; no PDF dependency.
    stream = b"""BT /F1 22 Tf 50 780 Td (HP DeskJet 3050 J610 - offline test) Tj ET
BT /F1 12 Tf 50 750 Td (A4 / text / colour / grayscale) Tj ET
0 1 1 rg 50 630 110 80 re f
1 0 1 rg 180 630 110 80 re f
1 1 0 rg 310 630 110 80 re f
0 0 0 rg 440 630 100 80 re f
0.5 0.5 0.5 rg 50 550 490 40 re f
0 0 0 RG 0.5 w 50 500 m 540 500 l S
BT /F1 10 Tf 50 470 Td (This file does not send a job to any printer.) Tj ET
"""
    if black_only:
        # A filled black rectangle exercises the lost-black-plane regression
        # without depending on font availability or text antialiasing.
        stream = b"0 0 0 rg 60 600 200 100 re f\n"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595.28 841.89] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"endstream",
    ]
    data = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data.extend(f"{index} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref = len(data)
    data.extend(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        data.extend(f"{offset:010} 00000 n \n".encode())
    data.extend(f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    path.write_bytes(data)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    report_path = OUT / "results.json"
    report_path.write_text(json.dumps({"status": "running", "hardware_tested": False}) + "\n")
    if not FILTER.is_file() or not PPD.is_file():
        raise SystemExit("Build the driver first: bash scripts/build-driver.sh")
    local_ppd = OUT / "local.ppd"
    local_ppd.write_text(PPD.read_text(encoding="latin-1").replace(
        "/Library/Printers/HPDeskjet3050/filter/hpcups", str(FILTER)), encoding="latin-1")
    pdf = OUT / "test-page.pdf"
    create_pdf(pdf)
    black_pdf = OUT / "black-regression.pdf"
    create_pdf(black_pdf, black_only=True)
    subprocess.run(["/usr/bin/codesign", "--verify", str(FILTER)], check=True)
    architecture = subprocess.check_output(["/usr/bin/lipo", "-archs", str(FILTER)], text=True).strip()
    if architecture != "arm64":
        raise SystemExit(f"Unexpected architecture: {architecture}")
    linked = subprocess.check_output(["/usr/bin/otool", "-L", str(FILTER)], text=True)
    for line in linked.splitlines()[1:]:
        library = line.strip().split(" (", 1)[0]
        if not library.startswith(("/usr/lib/", "/System/Library/")):
            raise SystemExit(f"Unexpected non-system dependency: {library}")
    results = []
    for name, colour, mode in [
        ("colour-normal", "RGB", "Normal"),
        ("black-normal", "KGray", "Normal"),
        ("gray-colour-inks", "CMYGray", "Normal"),
        ("colour-draft", "RGB", "FastDraft"),
        ("black-in-colour-mode", "RGB", "Normal"),
    ]:
        command = ["/usr/sbin/cupsfilter", "-p", str(local_ppd), "-e",
                   "-i", "application/pdf", "-m", "printer/HPDeskjet3050Test",
                   "-o", "PageSize=A4", "-o", f"ColorModel={colour}",
                   "-o", f"OutputMode={mode}", str(black_pdf if name == "black-in-colour-mode" else pdf)]
        with (OUT / f"{name}.pcl").open("wb") as output, (OUT / f"{name}.log").open("wb") as log:
            result = subprocess.run(command, stdout=output, stderr=log, timeout=120)
        data = (OUT / f"{name}.pcl").read_bytes()
        completed = data.endswith(b"\x1b*rC\x0c\x1bE\x1b%-12345X")
        # Skip each binary raster payload, so bytes inside it aren't parsed as commands.
        cursor, raster_bytes = 0, 0
        while match := re.search(rb"\x1b\*b(\d+)[WV]", data[cursor:]):
            count = int(match[1])
            cursor += match.end() + count
            raster_bytes += count
        passed = result.returncode == 0 and len(data) > 1000 and b"PCL3GUI" in data[:4096] and completed and raster_bytes > 0
        results.append({"name": name, "exit_code": result.returncode,
                        "bytes": len(data), "pcl3gui_header": b"PCL3GUI" in data[:4096],
                        "page_and_job_completed": completed,
                        "compressed_raster_bytes": raster_bytes,
                        "sha256": hashlib.sha256(data).hexdigest(), "passed": passed})
        print(f"{name}: {'PASS' if passed else 'FAIL'} ({len(data)} bytes)", flush=True)
    report = {"architecture": architecture, "hardware_tested": False,
              "filter_sha256": hashlib.sha256(FILTER.read_bytes()).hexdigest(),
              "tests": results}
    report["status"] = "passed" if all(test["passed"] for test in results) else "failed"
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    if not all(test["passed"] for test in results):
        raise SystemExit("Offline verification failed; inspect build/verification/*.log")


if __name__ == "__main__":
    try:
        main()
    except BaseException as exc:
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "results.json").write_text(json.dumps({
            "status": "failed", "error": str(exc), "hardware_tested": False
        }, indent=2) + "\n")
        raise
