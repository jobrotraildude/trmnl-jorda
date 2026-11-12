# TRMNL: Jordskjelv og vulkaner

To skjermer for TRMNL X (1872×1404, 16 gråtoner), tegnet av en GitHub Action og servert fra GitHub Pages. Ingen egen server.

| Fil | Data | Oppdateres |
|---|---|---|
| `quakes.png` | USGS, alle skjelv M2,5+ siste døgn | hver halvtime |
| `volcanoes.png` | Smithsonian/USGS Weekly Volcanic Activity Report (RSS) | hver halvtime (rapporten kommer onsdager) |

## Oppsett (ca. 10 minutter)

1. **Lag et nytt offentlig repo** på GitHub, f.eks. `trmnl-jorda`, og last opp alle filene. Behold mappen `.github/workflows/`. (Pages på private repo krever betalt GitHub-plan.)
2. **Slå på Pages:** *Settings → Pages → Build and deployment → Source:* velg **GitHub Actions**.
3. **Sett posisjonen din:** `HOME_LAT`/`HOME_LON` i `.github/workflows/render.yml` (brukes for «nærmest deg»).
4. **Kjør første gang:** *Actions → Tegn TRMNL-skjermer → Run workflow.* Vent til den er grønn (1–2 min).
5. **Sjekk bildene** i nettleseren:
   - `https://<brukernavn>.github.io/trmnl-jorda/quakes.png`
   - `https://<brukernavn>.github.io/trmnl-jorda/volcanoes.png`
6. **I TRMNL:** *Plugins → Image Display* → lim inn URL-en. Lag én plugin per bilde.
   - Jordskjelv: refresh hvert 30. min
   - Vulkaner: holder med noen ganger i døgnet
   - Legg begge i en playlist.

Bildet endrer seg bare når dataene endrer seg (klokkeslettet nede til høyre er tiden for *siste skjelv* / *rapportuka*, ikke tegnetidspunktet). Da tegner TRMNL ikke skjermen på nytt unødvendig.

## Test lokalt

```bash
pip install -r requirements.txt
mkdir -p fonts && base=https://raw.githubusercontent.com/google/fonts/main/ofl
curl -sSLf -o fonts/SpaceGrotesk.ttf      "$base/spacegrotesk/SpaceGrotesk%5Bwght%5D.ttf"
curl -sSLf -o fonts/IBMPlexMono-Bold.ttf    "$base/ibmplexmono/IBMPlexMono-Bold.ttf"
curl -sSLf -o fonts/IBMPlexMono-Regular.ttf "$base/ibmplexmono/IBMPlexMono-Regular.ttf"

python render.py --sample   # eksempeldata, ingen nett
python render.py --dump     # ekte data + utskrift av hva som ble tolket
```

Bildene havner i `site/`.

## Feilsøking

- **Vulkan mangler på kartet:** loggen sier `mangler koordinater for «X»`. Legg navnet til i `volcanoes.json` med `[lat, lon]` (finnes på volcano.si.edu).
- **Alle vulkaner havner som «pågående» (eller «nye»):** RSS-formatet kan ha endret seg. Kjør `python render.py --dump`, se hvordan tittel/beskrivelse ser ut, og juster regexen for `status` i `load_volcanoes()`.
- **Hvis en av feedene feiler,** avslutter skriptet med feil og Pages-siden blir *ikke* oppdatert. TRMNL fortsetter da å vise forrige versjon.
- **Planlagte kjøringer stopper etter 60 dager:** GitHub skrur av cron i repo uten aktivitet. Gjør en commit (hvilken som helst) eller trykk *Enable workflow* under Actions.

## Tilpasning

- Kartet er sentrert på Stillehavet (venstre kant 28° V), slik at Ildringen havner i midten. Endres med `LON0` i `render.py`.
- Størrelsen er låst til TRMNL X. For TRMNL OG (800×480) må layouten skaleres om.
- Fonter: Space Grotesk og IBM Plex Mono (SIL OFL), hentes automatisk av workflowen.
