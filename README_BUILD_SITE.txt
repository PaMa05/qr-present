Anleitung (Kurzfassung)

1) Voraussetzungen installieren (in deiner venv):
   pip install pandas openpyxl Pillow qrcode[pil]

2) Lege folgende Struktur an:
   entries.xlsx         # mit Spalten: ID;Bildernamen;Datum/Jahr;Beschreibung;Link
   images/              # enthält die in 'Bildernamen' referenzierten Dateien
   build_site.py

3) Seite bauen (mit korrekter Basis-URL für QR-Codes):
   python build_site.py --base-url "https://pama05.github.io/qr-present"

   Optional Etiketten-PDF (45x45 mm):
   python build_site.py --base-url "https://pama05.github.io/qr-present" --labels

4) Upload zu GitHub Pages:
   - Inhalt des Ordners 'site/' in dein Repo (root) hochladen
   - In GitHub: Settings → Pages → Deploy from a branch (main / root)
