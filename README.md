# Sonos-Türgong für Loxone

[![Lizenz: MIT](https://img.shields.io/badge/Lizenz-MIT-blue.svg)](LICENSE)

Spielt beim Klingeln einen Türgong über Sonos-Boxen ab, ausgelöst vom Loxone
Miniserver. Der Gong läuft als **Sonos-Ansage**: Laufende Musik wird nicht
unterbrochen, sondern kurz leiser gestellt und läuft danach normal weiter.

```
Klingeltaster ──► Loxone Miniserver ──HTTP──► sonos-doorbell ──Websocket──► Sonos-Boxen
                  (virtueller Ausgang)        (Docker)          (Port 1443)
```

## Funktionen

- Gong über eine oder mehrere Sonos-Boxen gleichzeitig, Räume frei wählbar
- Musik wird während des Gongs leiser gestellt und läuft danach weiter, bei
  jeder Quelle: Sonos-App, Spotify Connect, AirPlay, Radio, TV
- Lautstärke des Gongs einstellbar, global, pro Raum oder pro Aufruf
- Mehrere Gong-Dateien (`.mp3` oder `.wav`), pro Aufruf auswählbar
- Schutz vor Mehrfachklingeln (Sperrzeit)
- Kurze Reaktionszeit: Die Verbindungen zu den Boxen sind dauerhaft offen,
  beim Klingeln wird nur ein Befehl gesendet
- Läuft lokal, ohne Sonos-Konto, ohne Cloud und ohne LoxBerry
- Fertiger Docker-Compose-Stack, auch für Portainer mit Git-Anbindung

## Voraussetzungen

- Sonos-Boxen mit **S2**. Sie müssen die Ansagefunktion (`AUDIO_CLIP`)
  unterstützen; `GET /zones` zeigt, ob eine Verbindung zustande kommt.
- Ein Docker-Host im selben Netz wie die Boxen (NAS, Raspberry Pi, Server)
- Loxone Miniserver mit Loxone Config

## Schnellstart

```bash
git clone <repo-url> sonos-doorbell
cd sonos-doorbell
cp stack.env.example .env      # mindestens ADVERTISE_HOST eintragen
docker compose up -d --build
curl http://<host>:5005/zones  # alle Boxen sollten "connected": true zeigen
curl "http://<host>:5005/ring?zones=K%C3%BCche"   # Testgong
```

Danach Loxone einrichten, siehe [Einrichtung in Loxone Config](#einrichtung-in-loxone-config).

## Installation

### Mit Portainer (Git-Repository)

1. In Portainer: **Stacks → Add stack → Repository**.
2. Diese Felder ausfüllen:
   - **Name:** `sonos-doorbell`
   - **Repository URL:** URL dieses Repos. Bei einem privaten Repo
     „Authentication“ aktivieren und Benutzer und Token eintragen.
   - **Repository reference:** `refs/heads/main`
   - **Compose path:** `docker-compose.yml`
3. Unter **Environment variables** die Werte eintragen. Die Vorlage ist
   [`stack.env.example`](stack.env.example), sie lässt sich über
   „Load variables from .env file“ direkt laden. Pflicht ist nur
   `ADVERTISE_HOST`.
4. Optional **GitOps updates** aktivieren (Polling oder Webhook). Dann
   übernimmt Portainer Änderungen im Repo automatisch.
5. **Deploy the stack**. Portainer baut das Image auf dem Host und startet den
   Container.
6. Prüfen: `http://<host>:5005/zones` muss alle Boxen mit `"connected": true`
   zeigen.

Nach Änderungen im Repo (Code oder Gong-Dateien): im Stack **Pull and
redeploy** ausführen. Werden die Änderungen nicht übernommen, beim Redeploy
die Option zum erneuten Bauen bzw. Pullen des Images aktivieren.

### Mit Docker Compose

```bash
cp stack.env.example .env      # Werte anpassen
docker compose up -d --build
```

### Hinweis zum Netzwerk

Der Container läuft mit `network_mode: host`. Das ist nötig, damit die Boxen
automatisch gefunden werden (Multicast) und die Gong-Datei vom Host abrufen
können. Unter Linux funktioniert das direkt.

Bei **Docker Desktop (Windows/macOS)** muss Host-Networking in den
Einstellungen aktiviert sein. Alternativ:
- in `docker-compose.yml` `network_mode: host` durch `ports: ["5005:5005"]` ersetzen,
- die Boxen in `PLAYERS` mit festen IPs eintragen,
- `ADVERTISE_HOST` auf die LAN-IP des Rechners setzen.

## Konfiguration

Alle Einstellungen werden als Umgebungsvariablen gesetzt. Ohne Docker geht
alternativ eine `config.yaml` (Vorlage: [`config.example.yaml`](config.example.yaml),
Schlüssel in Kleinbuchstaben, z. B. `advertise_host`). Gesetzte
Umgebungsvariablen haben Vorrang vor der Datei.

| Variable | Bedeutung | Standard |
|---|---|---|
| `ADVERTISE_HOST` | LAN-IP des Docker-Hosts. Die Boxen laden darüber die Gong-Datei. **Pflicht.** | – |
| `PORT` | HTTP-Port des Dienstes | `5005` |
| `DEFAULT_ZONES` | Räume ohne `zones`-Parameter, kommagetrennt, Namen wie in der Sonos-App, oder `all` | `all` |
| `DEFAULT_SOUND` | Gong-Datei ohne Endung aus `sounds/` | `gong` |
| `DEFAULT_VOLUME` | Lautstärke des Gongs (0–100). Die Musiklautstärke bleibt unverändert. | `30` |
| `ZONE_VOLUMES` | Abweichende Gong-Lautstärke pro Raum, z. B. `Küche=40,Bad=20` | – |
| `PLAYERS` | Feste IPs, z. B. `Küche=<ip-küche>,Bad=<ip-bad>`. Ersetzt die automatische Suche (empfohlen). | – |
| `COOLDOWN_S` | Sperrzeit nach einem Klingeln in Sekunden | `3` |
| `DISCOVERY_REFRESH_S` | Abstand, in dem Boxen neu gesucht und Verbindungen geprüft werden | `300` |
| `LOG_LEVEL` | `DEBUG`, `INFO`, `WARNING` | `INFO` |
| `TZ` | Zeitzone für die Log-Zeitstempel | `Europe/Berlin` |

### Eigene Gongs

Gong-Dateien liegen im Ordner [`sounds/`](sounds) und werden ins Image
übernommen. So fügst du einen eigenen Gong hinzu:

1. Datei als `sounds/<name>.mp3` oder `sounds/<name>.wav` ablegen.
2. Ins Repo pushen und den Stack neu deployen.
3. Mit `?sound=<name>` aufrufen oder als `DEFAULT_SOUND` setzen.

Eine kurze Datei ohne Stille am Anfang sorgt für die schnellste Reaktion.
Der mitgelieferte `gong.wav` wurde mit [`tools/make_gong.py`](tools/make_gong.py)
erzeugt.

## Einrichtung in Loxone Config

1. **Virtueller Ausgang** anlegen (Peripherie → Virtuelle Ausgänge):
   - Bezeichnung: `Sonos-Türgong`
   - Adresse: `http://<docker-host-ip>:5005`
2. Darunter einen **Virtuellen Ausgang Befehl** anlegen:
   - Bezeichnung: `Gong`
   - Befehl bei EIN: `/ring` oder z. B. `/ring?zones=K%C3%BCche,Wohnzimmer&volume=35`
   - HTTP-Methode: `GET`
   - Befehl bei AUS: leer lassen
   - „Als Digitalausgang verwenden“: aktiv
3. Den Befehl mit dem Klingelsignal verbinden: Klingeltaster-Eingang oder der
   Ausgang „Klingel“ des Intercom-Bausteins. Bei Dauersignal einen
   Monoflop/Impuls davor setzen.
4. Für weitere Varianten (anderer Gong, nachts nur bestimmte Räume, leiser)
   weitere Befehle mit anderen Parametern anlegen und z. B. über den
   Nacht-Status umschalten.

## HTTP-Schnittstelle

| Aufruf | Wirkung |
|---|---|
| `GET /ring` | Gong in den `DEFAULT_ZONES` |
| `GET /ring?zones=Küche,Bad&sound=gong&volume=35` | Räume, Datei und Lautstärke für diesen Aufruf |
| `GET /zones` | Boxen mit IP, Player-ID und Verbindungsstatus |
| `GET /health` | Lebenszeichen, wird auch vom Docker-Healthcheck genutzt |
| `GET /sounds/<datei>` | Gong-Dateien; von hier laden die Boxen den Gong |

Antworten von `/ring`:

| Code | Bedeutung |
|---|---|
| `202` | Gong gestartet |
| `200` mit `"status": "ignored"` | Sperrzeit läuft noch |
| `404` | Gong-Datei oder Räume unbekannt |
| `422` | Ungültiger Parameter, z. B. Lautstärke außerhalb 0–100 |

Raumnamen sind unabhängig von Groß-/Kleinschreibung. Umlaute in der URL
sollten kodiert werden, z. B. `K%C3%BCche` für „Küche“.

## Wie es funktioniert

1. Beim Start ermittelt der Dienst die Boxen (feste IPs aus `PLAYERS` oder
   automatische Suche). Dann öffnet er zu jeder Box eine dauerhafte
   Websocket-Verbindung auf Port 1443.
2. Ruft Loxone `/ring` auf, antwortet der Dienst sofort mit `202`. Danach
   schickt er allen Ziel-Boxen gleichzeitig den Befehl `loadAudioClip` mit der
   Adresse der Gong-Datei und der Lautstärke.
3. Jede Box lädt die Datei per HTTP vom Dienst und spielt sie über die
   laufende Wiedergabe. Die Musik wird dabei von der Box selbst leiser
   gestellt und danach wiederhergestellt.

Genutzt wird die lokale Steuerschnittstelle der S2-Boxen, über die auch die
Sonos-App und Home Assistant Ansagen abspielen.

## Fehlersuche

| Problem | Ursache und Lösung |
|---|---|
| `/zones` zeigt `"connected": false` | Box nicht erreichbar oder Port 1443 blockiert (Firewall, getrenntes VLAN). Box muss S2 nutzen. |
| `/ring` liefert `202`, aber kein Ton | Die Box kann die Gong-Datei nicht laden. `ADVERTISE_HOST` prüfen und von einem anderen Gerät im LAN `http://<ADVERTISE_HOST>:5005/sounds/gong.wav` öffnen. Port 5005 in der Host-Firewall freigeben. |
| Log: `loadAudioClip abgelehnt` | Die Box lehnt die Ansage ab; der `errorCode` im Log nennt den Grund. |
| `404` mit `missing` | Raumname unbekannt. Die gültigen Namen zeigt `/zones`. |
| Keine Boxen gefunden | Multicast funktioniert nicht (z. B. Docker Desktop, VLAN). `PLAYERS` mit festen IPs setzen. |

Ausführliche Meldungen gibt es mit `LOG_LEVEL=DEBUG`. Die Zeit bis zum
gesendeten Befehl steht im Log als `Gong gesendet nach … ms`.

## Projektstruktur

```
app/
  main.py       HTTP-Endpunkte, Start und regelmäßige Aktualisierung
  chime.py      Klingel-Logik: Räume auflösen, Sperrzeit, parallel senden
  clip.py       Websocket-Client für die Sonos-Ansagen (audioClip)
  players.py    Liste der Boxen (feste IPs oder automatische Suche)
  config.py     Einstellungen aus Umgebungsvariablen oder config.yaml
sounds/         Gong-Dateien
tests/          Tests (pytest)
tools/          Hilfsskript zum Erzeugen des Beispiel-Gongs
```

## Entwicklung

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements-dev.txt   # Linux/macOS: .venv/bin/pip
.venv/Scripts/python -m pytest
```

Lokal ohne Docker starten:

```bash
CONFIG_PATH=config.yaml SOUNDS_DIR=sounds .venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 5005
```

## Haftungsausschluss

Dieses Projekt ist kein offizielles Produkt und steht in keiner Verbindung zu
Sonos, Inc. oder der Loxone Electronics GmbH. Sonos und Loxone sind Marken
ihrer jeweiligen Inhaber. Die genutzte lokale Schnittstelle der Boxen kann sich
mit Firmware-Updates ändern.

## Lizenz

[MIT](LICENSE)
