# PureThermal Y16 Server (Continuous Stream)

Stabilna wersja serwera do odczytu danych z kamery PureThermal (FLIR Lepton) przez USB-C.

## Funkcje:
- Ciągły odczyt `v4l2-ctl` z rury (pipe) w tle (eliminuje problem zawieszania USB)
- Generowanie obrazu termowizyjnego (paleta INFERNO) przez OpenCV
- Obliczanie temperatury punktowej w locie
- Strumień MJPEG i podgląd na żywo
- Zapis surowych klatek .raw (Y16) do archiwum co określony czas
- Obsługa przez systemd (`Restart=always`)
