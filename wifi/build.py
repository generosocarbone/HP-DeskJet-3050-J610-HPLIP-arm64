"""Build a local native HPLIP USB library; no installation or device access."""
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile


def main():
    root = Path(__file__).resolve().parent.parent
    source = root / "vendor" / "hplip-3.26.6"
    build = root / "build-wifi"
    dist = root / "dist-wifi"
    usb = Path("/opt/homebrew/opt/libusb")
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        raise SystemExit("Questa compilazione richiede macOS Apple Silicon.")
    if not (source / "io/hpmud/hpmud.c").is_file():
        raise SystemExit("Sorgenti HPLIP 3.26.6 mancanti in vendor/.")
    if not (usb / "lib/libusb-1.0.dylib").is_file():
        raise SystemExit("libusb non trovata in /opt/homebrew/opt/libusb.")
    debug_header = (source / "io/hpmud/hpmudi.h").read_text()
    import re
    if re.search(r"^\s*#\s*define\s+HPMUD_DEBUG\b", debug_header, re.MULTILINE):
        raise SystemExit("Compilazione rifiutata: HPMUD_DEBUG può registrare dati USB.")
    for directory in (build / "objects", build / "compat", build / "source", dist / "etc/hp", dist / "licenses"):
        directory.mkdir(parents=True, exist_ok=True)
    (build / "compat/malloc.h").write_text("#include <stdlib.h>\n")
    (dist / "etc/hp/hplip.conf").write_text("[dirs]\nhome=" + str(source) + "\n")
    sdk = subprocess.check_output(["/usr/bin/xcrun", "--sdk", "macosx", "--show-sdk-path"], text=True).strip()
    flags = ["/usr/bin/clang", "-arch", "arm64", "-isysroot", sdk, "-O2", "-std=gnu99",
             "-fcommon", "-fPIC", "-D_DARWIN_C_SOURCE", "-DHAVE_LIBUSB", '-DMUDNAME="hpmud"',
             '-DCONFDIR="' + str(dist / "etc/hp") + '"', "-Wno-deprecated-declarations",
             "-Wno-incompatible-pointer-types", "-include", "stdlib.h", "-include", "unistd.h"]
    for include in (build / "compat", source / "common", source / "io/hpmud", source,
                    usb / "include/libusb-1.0"):
        flags += ["-I", str(include)]
    names = ["io/hpmud/" + name + ".c" for name in ("hpmud", "mlc", "model", "pml", "dot4", "musb")]
    names.append("common/utils.c")
    objects = []
    for index, name in enumerate(names):
        input_file = source / name
        if name == "io/hpmud/musb.c":
            # Fix a swapped %d/%s argument pair only in our build copy. The
            # upstream failure path can otherwise crash while reporting an I/O error.
            original = input_file.read_text()
            before = 'BUG("unable to write data (len = %d) %s: %m\\n", msp->device[pc->dindex].uri, len);'
            after = 'BUG("unable to write data (len = %d) %s: %m\\n", len, msp->device[pc->dindex].uri);'
            if original.count(before) != 1:
                raise SystemExit("Sorgente musb.c inatteso: controllare la patch del messaggio I/O.")
            input_file = build / "source/musb.c"
            input_file.write_text(original.replace(before, after))
        obj = build / "objects" / f"{index:02d}-{Path(name).stem}.o"
        print("CC", name, flush=True)
        subprocess.run(flags + ["-c", str(input_file), "-o", str(obj)], check=True)
        objects.append(str(obj))
    library = dist / "libhpmud-j610.dylib"
    # Atomic publication preserves any existing process's mapped library.
    with tempfile.TemporaryDirectory(prefix=".wifi-link-", dir=dist) as temporary:
        candidate = Path(temporary) / library.name
        subprocess.run(["/usr/bin/clang", "-arch", "arm64", "-isysroot", sdk, "-dynamiclib",
                        "-Wl,-install_name,@rpath/libhpmud-j610.dylib", *objects,
                        str(usb / "lib/libusb-1.0.dylib"), "-lcups", "-framework", "CoreFoundation",
                        "-o", str(candidate)], check=True)
        subprocess.run(["/usr/bin/codesign", "--force", "--sign", "-", str(candidate)], check=True)
        candidate.replace(library)
    shutil.copyfile(source / "COPYING", dist / "licenses/HPLIP-COPYING")
    print(library)


if __name__ == "__main__":
    main()
