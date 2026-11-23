#!/usr/bin/env python3
"""Configure the J610 Wi-Fi over USB; passwords are entered only in a local TTY."""
import argparse
import getpass
import json
from pathlib import Path
import sys
import warnings

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from wifi.protocol import WifiDevice, WifiError, Network, profile_xml


def main():
    parser = argparse.ArgumentParser(description="Configura il Wi-Fi della HP DeskJet 3050 J610 tramite il cavo USB.")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--status", action="store_true", help="Legge stato e IP; non modifica impostazioni.")
    action.add_argument("--list", action="store_true", help="Elenca le reti visibili; richiede radio già accesa.")
    action.add_argument("--dry-run", action="store_true", help="Verifica il piano senza accedere alla stampante.")
    parser.add_argument("--ssid", help="Nome esatto della rete; altrimenti si sceglie dall'elenco.")
    args = parser.parse_args()
    if args.dry_run:
        profile_xml(Network(args.ssid or "Rete di esempio", "infrastructure", "wpa"), "example-only-password")
        print("Piano: USB → radio Wi-Fi accesa → ricerca reti → password locale → profilo → verifica IP.")
        print("Nessun accesso USB, nessuna password reale richiesta, nessuna modifica.")
        return
    if not args.status and not args.list and not sys.stdin.isatty():
        raise WifiError("Avvia lo script nel Terminale: nome rete e password devono essere inseriti localmente.")
    # Import after argument validation so help/dry-run work without native build.
    from wifi.transport import UsbTransport, TransportError
    try:
        with UsbTransport() as transport:
            device = WifiDevice(transport)
            device.discover()
            if args.status:
                print(json.dumps(device.status(), ensure_ascii=True, indent=2))
                return
            if not args.list:
                print("Attivo il Wi-Fi della stampante tramite USB e cerco le reti…", flush=True)
                device.power_on()
            networks = device.networks()
            if not networks:
                raise WifiError("Nessuna rete visibile. Verifica che il router abbia una rete a 2,4 GHz attiva.")
            for number, net in enumerate(networks, 1):
                print(f"{number}. {json.dumps(net.ssid, ensure_ascii=False)} — {net.encryption}, canale {net.channel or '?'}")
            if args.list:
                return
            if args.ssid:
                matches = [net for net in networks if net.ssid == args.ssid]
                if len(matches) != 1:
                    raise WifiError("Il nome indicato non corrisponde a una sola rete visibile; riprova senza --ssid.")
                selected = matches[0]
            else:
                choice = input("Numero della rete da configurare: ").strip()
                if not choice.isdecimal() or not 1 <= int(choice) <= len(networks):
                    raise WifiError("Selezione non valida; nessuna credenziale inviata.")
                selected = networks[int(choice) - 1]
            # Validate capability before asking for a password.
            profile_xml(selected, "validation-placeholder")
            password = ""
            if selected.encryption.lower() != "none":
                with warnings.catch_warnings():
                    warnings.simplefilter("error", getpass.GetPassWarning)
                    try:
                        password = getpass.getpass("Password Wi-Fi (non verrà mostrata né salvata sul Mac): ")
                    except getpass.GetPassWarning:
                        raise WifiError("Il terminale non può nascondere la password; configurazione interrotta.") from None
            print(f"Configuro {json.dumps(selected.ssid, ensure_ascii=False)}…", flush=True)
            try:
                device.associate(selected, password)
            finally:
                password = ""
            print("Profilo accettato. Attendo l'indirizzo IP (fino a due minuti)…", flush=True)
            status = device.wait_connected(selected.ssid)
            print("La stampante comunica questi indirizzi Wi-Fi: " + ", ".join(status["ipv4"]))
            print("Configurazione completata. La coda di stampa USB e lo scanner USB restano disponibili.")
            print("Per stampare senza cavo occorre configurare anche una coda di rete sul Mac.")
    except TransportError as error:
        raise WifiError(str(error)) from None


if __name__ == "__main__":
    try:
        main()
    except (WifiError, OSError) as error:
        sys.exit(f"Errore: {error}")
    except (KeyboardInterrupt, EOFError):
        sys.exit("\nOperazione interrotta. Usa --status per controllare la configurazione attuale.")
