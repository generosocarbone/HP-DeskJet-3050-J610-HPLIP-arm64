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

## Configurazione Wi-Fi tramite USB

La J610 dichiara `wifi-config=3` nel database HP: supporta l'invio del profilo Wi-Fi tramite LEDM su USB, senza usare il display o i pulsanti della stampante. Lo script riproduce la sequenza di `vendor/hplip-3.26.6/base/LedmWifi.py`.

Lasciare la stampante accesa e collegata via USB. Nel **Terminale del Mac**, senza `sudo`:

```sh
python3 /Users/generosocarbone/dev/driver/scripts/configure-wifi.py
```

In modalità interattiva lo script accende la radio se necessario, elenca le reti visibili, chiede il numero della rete e la password nascosta, invia il profilo alla stampante e attende fino a due minuti per l'associazione e l'indirizzo IPv4. La password digitata non viene accettata come argomento, stampata o salvata in file sul Mac; la stampante la memorizza nel proprio profilo per riconnettersi.

Per preselezionare una rete visibile:

```sh
python3 scripts/configure-wifi.py --ssid "Nome della rete"
```

### Configurazione da file

La modalità `--config` legge SSID e password da un file JSON locale, senza richiedere input interattivo. Anche questa modalità configura la stampante tramite USB, senza usare il suo pannello.

In questo workspace è già presente `wifi-config.json`, con campi vuoti da compilare e permessi `600`. Il file e le varianti `wifi-config.*.json` sono esclusi da Git; viene versionato solo `wifi-config.example.json`, che contiene valori di esempio. Non inserire credenziali reali nel file di esempio.

Formato del file:

```json
{
  "ssid": "Nome_della_rete",
  "password": "Password_della_rete"
}
```

Su un nuovo checkout, dalla cartella del progetto, creare la propria copia:

```sh
cp wifi-config.example.json wifi-config.json
chmod 600 wifi-config.json
```

Modificare `wifi-config.json` con nome e password esatti, poi verificare il file senza accedere alla stampante:

```sh
python3 scripts/configure-wifi.py --config wifi-config.json --dry-run
```

Per applicarlo, con la stampante accesa e collegata via USB:

```sh
python3 scripts/configure-wifi.py --config wifi-config.json
```

Il nome deve corrispondere a una sola rete visibile. Il tipo di sicurezza viene letto dalla stampante; se la rete è protetta ma la password è vuota, oppure la rete è aperta e il file contiene una password, il profilo non viene inviato. Per una rete aperta usare `"password": ""`.

Il file viene validato prima di aprire il collegamento USB: JSON UTF-8, soli campi `ssid` e `password`, nessun campo duplicato, dimensione massima 8 KiB e nessun permesso per gruppo/altri utenti. Le credenziali non sono riportate nei messaggi, neppure in caso di errore. In questa modalità la password resta nel file JSON che hai compilato; lo script non ne crea altre copie. Se scegli un percorso diverso, assicurati che anche quel file sia escluso da Git.

`--config` è alternativo a `--ssid` e non si combina con `--status` o `--list`. Senza `--config`, la procedura interattiva continua a funzionare come prima.

Comandi senza modifica della configurazione:

```sh
python3 scripts/configure-wifi.py --status   # radio, associazione, SSID e IP
python3 scripts/configure-wifi.py --list     # reti rilevate; radio già accesa
python3 scripts/configure-wifi.py --dry-run  # piano offline, nessun accesso USB
```

Supporto attuale: reti visibili a 2,4 GHz, WPA/WPA2 personali con passphrase ASCII di 8–63 caratteri, oppure reti aperte. Non implementa WEP, reti nascoste, autenticazione aziendale o WPA3 esclusivo. Conserva i valori di sicurezza segnalati dalla stampante (sul modello provato: `WPA_PSK`).

**Verifiche eseguite:** lettura reale di radio e stato associazione; ricerca reale delle reti tramite USB; 21 test automatici del payload, della gestione HTTP e degli errori. L'utente ha poi eseguito lo script interattivo: profilo accettato, associazione riuscita e indirizzo `192.168.1.106`. Il Mac raggiunge la stampante sulla rete; modello e numero di serie letti dal dispositivo coincidono con la J610 USB.

Il firmware della J610 risponde HTTP 405 a `GET /IoMgmt/Adapters/Wifi0`; lo stato viene quindi letto da `/IoMgmt/Adapters`, incluso `IsConnected`. Un profilo accettato o un vecchio IP, da soli, non sono considerati un collegamento riuscito. Le scritture dall'esito incerto non vengono ritentate automaticamente.

Lo script di configurazione Wi-Fi non crea automaticamente una coda di stampa di rete sul Mac. Su questo Mac la coda è stata successivamente aggiunta come descritto sotto. Il programma scanner attuale continua a usare USB.

Per ricompilare il componente locale e ripetere i test:

```sh
bash scripts/build-wifi.sh
python3 -m unittest discover -s tests -v
```

Il componente usa `libusb` già presente e percorsi verso il database HPLIP nel progetto: dopo uno spostamento della cartella occorre ricompilare. Non richiede installazioni di sistema. Una correzione a un messaggio d'errore USB di HPLIP viene applicata soltanto alla copia di compilazione, lasciando intatti i sorgenti originali.

## Stampa via Wi-Fi

Nelle applicazioni scegliere **HP DeskJet 3050 J610 — Wi-Fi**. La coda CUPS è `HP_Deskjet_3050_J610_WiFi`, indirizzata a `socket://192.168.1.106:9100`, con lo stesso driver HPLIP arm64 già collaudato via USB. Impostazioni predefinite: A4 e `KGray` (cartuccia nera); la coda non è condivisa e non è stata impostata come stampante predefinita. Le code USB restano disponibili.

**Prova hardware riuscita:** il lavoro 18 risulta completato in CUPS e l'utente ha confermato che la pagina è uscita correttamente. La destinazione `socket://` usa effettivamente la rete anche quando il cavo USB è ancora collegato.

L'indirizzo è assegnato dal router e potrebbe cambiare. In tal caso riservare `192.168.1.106` alla stampante nelle impostazioni DHCP del router oppure aggiornare la coda con il nuovo IP verificato:

```sh
lpadmin -p HP_Deskjet_3050_J610_WiFi -v socket://NUOVO_IP:9100
```

Il comando può richiedere privilegi amministrativi su altri Mac. Questa configurazione riguarda la stampa: per il nostro comando di scansione serve ancora il cavo USB.

## Sorgenti e provenienza

Il codice HP originale è conservato in `vendor/hplip-3.26.6`; la compilazione lavora su copie. Fonte: [download HPLIP ufficiale](https://developers.hp.com/hp-linux-imaging-and-printing/gethplip), archivio `https://downloads.sourceforge.net/project/hplip/hplip/3.26.6/hplip-3.26.6.tar.gz`.

SHA-256 dell'archivio scaricato in questa sessione:

```text
5fb2235a9cb6ec07cb4786c4066b151359c301324d54aaabf69ae7eef35606b3
```

Questo hash identifica il download usato; non è una firma del produttore verificata indipendentemente.

Per ricreare `vendor/`, scaricare l'archivio, verificare l'hash ed estrarlo nella cartella. Non eseguire gli installer Linux contenuti nel tarball.

La [tabella HP](https://developers.hp.com/hp-linux-imaging-and-printing/supported_devices/index) include il modello esatto. Le [FAQ HPLIP](https://developers.hp.com/hp-linux-imaging-and-printing/faqs) chiariscono che HP non collauda il progetto su macOS/Darwin. Le licenze del codice originale sono nei file sorgenti e in `vendor/hplip-3.26.6/COPYING`; le copie per il filtro compilato sono in `dist/licenses`.
