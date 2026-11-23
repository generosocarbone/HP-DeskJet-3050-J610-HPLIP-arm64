# HP DeskJet 3050 J610 su macOS Apple Silicon

Adattamento locale di HP HPLIP 3.26.6 per la **DeskJet 3050 J610**, sviluppato e compilato su macOS 26.6.2 arm64. Non è un driver ufficiale HP per macOS e non riguarda la 3050A J611 o la LaserJet 3050.

## Diagnosi del 23 novembre 2026

- La coda originale `HP_Deskjet_3050_J610_series` usa il profilo generico `HP DeskJet Series` e il filtro `rastertohp`.
- Il profilo specifico HP della J610 richiede `hpcups` e il linguaggio `pcl3gui2`.
- Non erano presenti componenti HP in `/Library/Printers` né driver scanner in `/Library/Image Capture/Devices`.
- Inizialmente la stampante era scollegata. Successivamente rilevata via USB, VID:PID `03f0:9311`.
- L'utente conferma che la fotocopia autonoma funziona.

Il vecchio [pacchetto HP 5.1.1 distribuito da Apple](https://support.apple.com/en-us/106385) è dichiarato incompatibile con macOS 12 e successivi.

## Stampa

Il filtro usa il codice HP per conversione raster, compressione e protocollo. La factory è limitata al linguaggio della J610; non include componenti di altre famiglie di stampanti. Il trasporto USB resta quello di macOS/CUPS.

È stata corretta un'incompatibilità nel percorso colore: il profilo originale richiede RGBW, mentre il motore PCL3GUI2 di questa versione trasmette soltanto RGB. Il testo nero veniva separato in un piano poi scartato. Il profilo adattato richiede RGB a 24 bit, mantenendo il nero e i colori; le opzioni di scala di grigi conservano i comandi specifici della stampante.

Verifica offline: cinque conversioni completate (colore normale, nero, grigi con inchiostri colore, bozza, rettangolo nero in modalità colore). I test controllano dati raster non vuoti e terminatori di pagina/lavoro oltre al codice di uscita. Il PPD supera `cupstestppd` (restano avvisi del profilo HP sui nomi di alcuni formati carta).

**Verifica hardware:** installazione completata dall'utente, lavoro CUPS 17 completato e stampa del nero confermata dall'utente. La cartuccia a colori è assente, quindi la stampa a colori resta da verificare. Per stampare dalle app scegliere **HP DeskJet 3050 J610 — HPLIP arm64**.

Artefatti:

- `dist/filter/hpcups`: eseguibile nativo arm64, firmato ad hoc, dipendente soltanto da librerie di sistema.
- `dist/ppd/hp-deskjet_3050_j610_series.ppd`: profilo del modello, carta A4 e percorso assoluto del filtro.
- `scripts/build-driver.sh`: compilazione riproducibile senza installazione.
- `scripts/test-driver.py`: verifica reale della catena PDF → raster di macOS → PCL3GUI, senza inviare lavori alla stampante.
- `scripts/install-driver.sh`: anteprima e installazione in una coda separata.

Per ricompilare e verificare:

```sh
bash scripts/build-driver.sh
python3 scripts/test-driver.py
```

I risultati e i log sono in `build/verification/`. Il superamento dei test offline non certifica il risultato su carta, la resa cromatica o tutte le opzioni del dispositivo.

Per vedere il piano di installazione:

```sh
bash scripts/install-driver.sh
```

Per installare il candidato:

```sh
sudo bash scripts/install-driver.sh --apply
```

L'installazione crea `/Library/Printers/HPDeskjet3050` e la coda `HP_Deskjet_3050_J610_native`, denominata **HP DeskJet 3050 J610 — HPLIP arm64**. Conserva la coda originale, non cambia la stampante predefinita e non avvia stampe. Richiede privilegi di amministratore perché scrive nella cartella dei driver di sistema. Se il nome o la destinazione esistono già, si ferma.

Una pagina di prova si invia esplicitamente con:

```sh
lp -d HP_Deskjet_3050_J610_native -o PageSize=A4 build/verification/test-page.pdf
```

## Scanner

È stato compilato anche un frontend nativo per il protocollo scanner LEDM della J610, usando i sorgenti HP `hpmud`, `ledm`, `bb_ledm` e il decoder immagini `ip`. Non richiede installazione di SANE. L'unico componente omesso è la notifica di stato D-Bus specifica di Linux.

**Verifica hardware:** apertura USB e lettura opzioni riuscite; acquisizione a colori riuscita a 100 dpi, 850 × 1169 pixel. Il PNG è stato ispezionato: contiene un'immagine leggibile del foglio. I risultati sono in `scans/prova-j610.png` e `scans/prova-j610.pdf`. Lo scanner acquisisce i colori anche senza cartuccia colore.

Con stampante accesa, USB collegata e foglio sul vetro, eseguire:

```sh
python3 /Users/generosocarbone/dev/driver/scripts/scan.py
```

Il comando salva un PDF in `scans/` con data e ora. Per scegliere il file:

```sh
python3 scripts/scan.py scans/documento.pdf
python3 scripts/scan.py scans/documento.png
```

Anche il comando completo è stato provato sull'hardware: `scans/verifica-completa.pdf` acquisito e convertito correttamente a 100 dpi.

Acquisisce una pagina a colori scegliendo una risoluzione bassa supportata dal dispositivo (100 dpi sulla J610 provata). Rifiuta di sovrascrivere file esistenti. Per ricompilare:

```sh
bash scripts/build-scanner.sh
dist-scanner/j610-scanner-probe --self-test
```

Limiti attuali: scansione via comando, USB e piano fisso; nessuna integrazione con **Acquisizione Immagine**, nessuna prova via Wi-Fi. Il componente scanner dipende dalla `libusb` già presente in `/opt/homebrew/opt/libusb` e dal database del modello in `vendor/`. Conservare questa cartella di progetto; dopo uno spostamento occorre ricompilare. In caso di timeout, interrompere eventuali lavori e riavviare la stampante prima di riprovare.

Il database HP identifica la J610 come `scan-type=7` (LEDM), senza plugin binario proprietario. Un backend HPLIP/SANE non appare automaticamente in Acquisizione Immagine: l'integrazione con quell'app richiede un ulteriore componente.

Come alternativa già distribuita, il produttore di [VueScan dichiara supporto specifico per la J610 su macOS via USB](https://www.hamrick.com/vuescan/hp_deskjet_3050_j610.html). Questa indicazione non costituisce una prova sul dispositivo dell'utente.

## Sorgenti e provenienza

Il codice HP originale è conservato in `vendor/hplip-3.26.6`; la compilazione lavora su copie. Fonte: [download HPLIP ufficiale](https://developers.hp.com/hp-linux-imaging-and-printing/gethplip), archivio `https://downloads.sourceforge.net/project/hplip/hplip/3.26.6/hplip-3.26.6.tar.gz`.

SHA-256 dell'archivio scaricato in questa sessione:

```text
5fb2235a9cb6ec07cb4786c4066b151359c301324d54aaabf69ae7eef35606b3
```

Questo hash identifica il download usato; non è una firma del produttore verificata indipendentemente.

Per ricreare `vendor/`, scaricare l'archivio, verificare l'hash ed estrarlo nella cartella. Non eseguire gli installer Linux contenuti nel tarball.

La [tabella HP](https://developers.hp.com/hp-linux-imaging-and-printing/supported_devices/index) include il modello esatto. Le [FAQ HPLIP](https://developers.hp.com/hp-linux-imaging-and-printing/faqs) chiariscono che HP non collauda il progetto su macOS/Darwin. Le licenze del codice originale sono nei file sorgenti e in `vendor/hplip-3.26.6/COPYING`; le copie per il filtro compilato sono in `dist/licenses`.
