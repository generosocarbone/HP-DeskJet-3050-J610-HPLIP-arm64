#!/bin/bash
# Build only the J610 print-language path; do not install or contact a printer.
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
UPSTREAM_DIR="$PROJECT_DIR/vendor/hplip-3.26.6"
BUILD_DIR="$PROJECT_DIR/build/native-print"
DIST_DIR="$PROJECT_DIR/dist"
SDK_DIR="$(xcrun --sdk macosx --show-sdk-path)"
if [[ "$(uname -s)" != Darwin || "$(uname -m)" != arm64 ]]; then
  echo "This build targets Apple Silicon macOS." >&2
  exit 1
fi
if [[ ! -f "$UPSTREAM_DIR/prnt/hpcups/HPCupsFilter.cpp" ]]; then
  echo "Missing HPLIP 3.26.6 sources: $UPSTREAM_DIR" >&2
  exit 1
fi
mkdir -p "$BUILD_DIR/source/prnt/hpcups" "$BUILD_DIR/source/common" "$BUILD_DIR/obj" "$DIST_DIR/filter" "$DIST_DIR/ppd" "$DIST_DIR/licenses"
# Work on copies: the downloaded upstream source remains intact.
cp "$UPSTREAM_DIR/prnt/hpcups/"*.h "$BUILD_DIR/source/prnt/hpcups/"
cp "$UPSTREAM_DIR/common/utils.h" "$BUILD_DIR/source/common/utils.h"
cp "$UPSTREAM_DIR/common/utils.c" "$BUILD_DIR/source/common/utils.c"
SOURCES=(HPCupsFilter dbuscomm Compressor Mode9 Mode10 ErnieFilter Encapsulator Pcl3Gui2 Job Pipeline Processor RasterSender SystemServices)
for name in "${SOURCES[@]}"; do
  # APFS often ignores case, so utils.h otherwise resolves to hpcups/Utils.h.
  sed 's|#include "utils.h"|#include "../../common/utils.h"|' \
    "$UPSTREAM_DIR/prnt/hpcups/$name.cpp" > "$BUILD_DIR/source/prnt/hpcups/$name.cpp"
done
FLAGS=(-arch arm64 -isysroot "$SDK_DIR" -mmacosx-version-min=11.0 -O2
  -DAPDK_LITTLE_ENDIAN -DDISABLE_IMAGEPROCESSOR -D_DARWIN_C_SOURCE '-DCONFDIR="/etc/hp"'
  -include unistd.h -Wno-deprecated-declarations
  -I"$BUILD_DIR/source/prnt/hpcups" -I"$BUILD_DIR/source/common"
  -I"$UPSTREAM_DIR/io/hpmud")
OBJECTS=()
for name in "${SOURCES[@]}"; do
  echo "Compiling $name"
  /usr/bin/clang++ "${FLAGS[@]}" -std=c++11 -c \
    "$BUILD_DIR/source/prnt/hpcups/$name.cpp" -o "$BUILD_DIR/obj/$name.o"
  OBJECTS+=("$BUILD_DIR/obj/$name.o")
done
/usr/bin/clang "${FLAGS[@]}" -std=gnu11 -c "$BUILD_DIR/source/common/utils.c" -o "$BUILD_DIR/obj/common_utils.o"
/usr/bin/clang++ "${FLAGS[@]}" -std=c++11 -c "$PROJECT_DIR/src/EncapsulatorFactoryJ610.cpp" -o "$BUILD_DIR/obj/factory_j610.o"
/usr/bin/clang++ -arch arm64 -isysroot "$SDK_DIR" -mmacosx-version-min=11.0 \
  "${OBJECTS[@]}" "$BUILD_DIR/obj/common_utils.o" "$BUILD_DIR/obj/factory_j610.o" \
  -lcups -o "$DIST_DIR/filter/hpcups"
/usr/bin/codesign --force --sign - "$DIST_DIR/filter/hpcups"
# Pcl3Gui2 sends only the RGB plane. With RGBW17, extractBlackPixels moves
# solid black into an ignored K plane. Request RGB24 (space1) to retain it.
/usr/bin/gzip -cd "$UPSTREAM_DIR/ppd/hpcups/hp-deskjet_3050_j610_series.ppd.gz" | \
  sed -e 's|\*cupsFilter: "application/vnd.cups-raster 0 hpcups"|*cupsFilter: "application/vnd.cups-raster 0 /Library/Printers/HPDeskjet3050/filter/hpcups"|' \
      -e 's|\*NickName: "HP Deskjet 3050 j610 Series, hpcups 3.26.6"|*NickName: "HP Deskjet 3050 J610, hpcups 3.26.6 (arm64)"|' \
      -e 's|\*DefaultPageSize: Letter|*DefaultPageSize: A4|' \
      -e 's|\*DefaultPageRegion: Letter|*DefaultPageRegion: A4|' \
      -e 's|\*DefaultImageableArea: Letter|*DefaultImageableArea: A4|' \
      -e 's|\*DefaultPaperDimension: Letter|*DefaultPaperDimension: A4|' \
      -e 's|/cupsColorSpace 17/|/cupsColorSpace 1/|' \
  > "$DIST_DIR/ppd/hp-deskjet_3050_j610_series.ppd"
cp "$UPSTREAM_DIR/COPYING" "$DIST_DIR/licenses/HPLIP-COPYING"
cp "$PROJECT_DIR/licenses/LINKED-SOURCE-NOTICES.txt" "$DIST_DIR/licenses/"
/usr/bin/file "$DIST_DIR/filter/hpcups"
/usr/bin/otool -L "$DIST_DIR/filter/hpcups"
echo "Built: $DIST_DIR/filter/hpcups (not installed)"
