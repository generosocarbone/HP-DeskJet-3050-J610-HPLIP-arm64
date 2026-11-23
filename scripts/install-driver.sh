#!/bin/bash
# Installs only this project's print filter and a new, separate CUPS queue.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST=/Library/Printers/HPDeskjet3050
QUEUE=HP_Deskjet_3050_J610_native
OLD_QUEUE=HP_Deskjet_3050_J610_series
FILTER="$ROOT/dist/filter/hpcups"
PPD="$ROOT/dist/ppd/hp-deskjet_3050_j610_series.ppd"
APPLY=0
URI=""

while [ "$#" -gt 0 ]; do
  case "$1" in
    --apply) APPLY=1; shift ;;
    --uri) [ "$#" -ge 2 ] || { echo 'Manca il valore di --uri.' >&2; exit 2; }; URI="$2"; shift 2 ;;
    -h|--help)
      echo 'Uso: bash scripts/install-driver.sh [--uri usb://HP/...] [--apply]'
      echo 'Senza --apply mostra soltanto il piano. --apply richiede sudo.'
      exit 0 ;;
    *) echo "Argomento sconosciuto: $1" >&2; exit 2 ;;
  esac
done

[ -x "$FILTER" ] && [ -f "$PPD" ] || { echo 'Compilare prima con scripts/build-driver.sh.' >&2; exit 1; }
/usr/bin/file "$FILTER" | /usr/bin/grep -q 'arm64' || { echo 'Il filtro non è arm64.' >&2; exit 1; }
/usr/bin/codesign --verify "$FILTER"
/usr/bin/grep -q 'HP Deskjet 3050 j610 Series' "$PPD"
/usr/bin/grep -q '/Library/Printers/HPDeskjet3050/filter/hpcups' "$PPD"

if [ -z "$URI" ]; then
  # macOS CUPS may use the system UI language even when LC_ALL=C.
  URI="$(/usr/bin/lpstat -v "$OLD_QUEUE" | /usr/bin/sed -n 's|^[^:]*: \(usb://.*\)$|\1|p')"
fi
case "$URI" in
  usb://HP/Deskjet%203050%20J610%20series\?*) ;;
  *) echo 'URI USB della J610 non trovato. Specificarlo con --uri usando lpstat -v.' >&2; exit 1 ;;
esac

echo "Destinazione del driver: $DEST"
echo "Nuova coda: $QUEUE (A4, non condivisa)"
echo "Dispositivo: ${URI%%\?*}?serial=[omesso]"
echo "La coda esistente $OLD_QUEUE resta disponibile. Non viene inviata alcuna stampa."
if [ "$APPLY" -eq 0 ]; then
  echo 'Solo anteprima: nessuna modifica effettuata.'
  exit 0
fi

[ "$(id -u)" -eq 0 ] || { echo 'Per installare: sudo bash scripts/install-driver.sh --apply' >&2; exit 1; }
[ ! -e "$DEST" ] && [ ! -L "$DEST" ] || { echo "$DEST esiste già: installazione interrotta." >&2; exit 1; }
if /usr/bin/lpstat -p "$QUEUE" >/dev/null 2>&1; then
  echo "La coda $QUEUE esiste già: installazione interrotta." >&2; exit 1
fi
/usr/bin/lpstat -p >/dev/null || {
  echo 'CUPS non disponibile: nessun file installato.' >&2; exit 1;
}

rollback() {
  echo 'Installazione fallita; rimuovo soltanto i file e la nuova coda creati da questo tentativo.' >&2
  /usr/sbin/lpadmin -x "$QUEUE" >/dev/null 2>&1 || true
  /bin/rm -f "$DEST/filter/hpcups" "$DEST/ppd/hp-deskjet_3050_j610_series.ppd"
  /bin/rmdir "$DEST/filter" "$DEST/ppd" "$DEST" 2>/dev/null || true
}
trap rollback ERR

/usr/bin/install -d -o root -g wheel -m 755 "$DEST" "$DEST/filter" "$DEST/ppd"
/usr/bin/install -o root -g wheel -m 755 "$FILTER" "$DEST/filter/hpcups"
/usr/bin/install -o root -g wheel -m 644 "$PPD" "$DEST/ppd/hp-deskjet_3050_j610_series.ppd"
/usr/sbin/lpadmin -p "$QUEUE" -E -v "$URI" \
  -P "$DEST/ppd/hp-deskjet_3050_j610_series.ppd" \
  -D 'HP DeskJet 3050 J610 — HPLIP arm64' \
  -o PageSize=A4 -o printer-is-shared=false -o printer-error-policy=stop-printer
/usr/bin/lpstat -p "$QUEUE"
trap - ERR
echo 'Driver installato. La verifica su carta resta da eseguire.'
