cat << 'EOF' > ~/thermal_server_v2/README.md
# PureThermal Y16 Web Server

Serwer webowy (oparty na mikroframeworku Flask) do obsługi kamer termowizyjnych **FLIR Lepton** na płytkach **PureThermal** (podłączanych przez USB-C). Zapewnia podgląd na żywo, odczyt temperatury w locie oraz archiwizację nagrań z osią czasu (timeline).

## Architektura i stabilność (Rozwiązanie problemu USB)
Wiele standardowych implementacji odpytujących kamery UVC/PureThermal w pętli powoduje zawieszanie się kontrolera USB lub firmware'u kamery. 
Ten projekt rozwiązuje ten problem poprzez **rozdzielenie procesu odczytu od serwera www**:
1. Osobny wątek w tle nieprzerwanie czyta surowy strumień z `v4l2-ctl` (`--stream-to=-`) prosto do pamięci RAM.
2. Serwer Flask serwuje najświeższą klatkę z pamięci RAM wielu klientom jednocześnie, bez dodatkowego obciążania sprzętu.
3. Archiwum asynchronicznie zrzuca klatkę na dysk (np. co 30 sekund).

## Główne funkcje
* **Live View (MJPEG):** Płynny strumień z nałożoną paletą barw (INFERNO).
* **Radiometria punktowa:** Kliknięcie w dowolny punkt na obrazie (Live i Archiwum) przelicza surowe wartości Y16 na stopnie Celsjusza.
* **Timeline Archiwum:** Zapisywanie ramek `.raw` i wygodna nawigacja po historycznych klatkach za pomocą suwaka czasu.
* **Plug & Play:** Całkowicie automatyczny instalator i autostart wraz z systemem (systemd).
* **Odporność na błędy:** Jeśli kamera zostanie odłączona, system czeka w tle. Po jej ponownym podpięciu, serwer automatycznie wznawia strumieniowanie i zapis.

---

## 🚀 Instrukcja instalacji (Ubuntu)

Instalacja sprowadza się do pobrania repozytorium i uruchomienia skryptu, który sam pobierze zależności systemu, ustawi ścieżki i zainstaluje usługę systemową.

```bash
# 1. Zaktualizuj system i zainstaluj gita (jeśli nie masz)
sudo apt update && sudo apt install -y git

# 2. Sklonuj repozytorium
git clone [https://github.com/Igor-Mie/thermal_server_v2.git](https://github.com/Igor-Mie/thermal_server_v2.git)

# 3. Wejdź do katalogu i uruchom instalator
cd thermal_server_v2
chmod +x install.sh
./install.sh
