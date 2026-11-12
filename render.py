#!/usr/bin/env python3
"""
Tegner TRMNL X-skjermer (16 gråtoner) for jordskjelv og vulkaner, i alle fire TRMNL-layouter:

  full             1872x1404   quakes.png / volcanoes.png  (også *_full.png)
  half_horizontal  1872x702    quakes_half_horizontal.png  / volcanoes_half_horizontal.png
  half_vertical     936x1404   quakes_half_vertical.png    / volcanoes_half_vertical.png
  quadrant          936x702    quakes_quadrant.png         / volcanoes_quadrant.png

I tillegg skrives status.json med versjonsnøkler, slik at en privat TRMNL-plugin
(polling) vet når bildene har endret seg.

Data: USGS (alle skjelv M2.5+ siste døgn) og Smithsonian/USGS Weekly Volcanic Activity Report.

Bruk:
  python render.py                 # henter ferske data, skriver til ./site/
  python render.py --sample        # innebygde eksempeldata (ingen nett)
  python render.py --dump          # skriver også ut det som ble tolket fra feedene
  python render.py --out mappe     # annen utmappe

Miljøvariabler (valgfrie):
  HOME_LAT, HOME_LON   – din posisjon, brukes for «nærmest deg» (standard Oslo)
  TZ_NAME              – tidssone for klokkeslett (standard Europe/Oslo)
"""
import argparse, datetime as dt, hashlib, json, math, os, re, shutil, sys, unicodedata, urllib.request
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFont
from global_land_mask import globe

HERE = os.path.dirname(os.path.abspath(__file__))
FONTS = os.path.join(HERE, 'fonts')

USGS_URL = 'https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/2.5_day.geojson'
GVP_URL = 'https://volcano.si.edu/news/WeeklyVolcanoRSS.xml'
UA = 'trmnl-jorda/1.1 (personal e-ink display)'

HOME_LAT = float(os.environ.get('HOME_LAT', '59.91'))
HOME_LON = float(os.environ.get('HOME_LON', '10.75'))
TZ = ZoneInfo(os.environ.get('TZ_NAME', 'Europe/Oslo'))

LAYOUTS = {
    'full': (1872, 1404),
    'half_horizontal': (1872, 702),
    'half_vertical': (936, 1404),
    'quadrant': (936, 702),
}

SS = 2                                   # supersampling for kart
LON0, LAT0, LAT1 = -28.0, 82.0, -58.0    # Stillehavet i midten, venstre kant 28°V


def gray(level):
    """level 0 (hvit) .. 15 (svart) -> 8-bit gråverdi"""
    return 255 - level * 17


def quantize16(img):
    return img.point(lambda v: int(round(v / 17.0)) * 17)


# ---------- fonter ----------
_font_cache = {}


def font(kind, size, weight=400):
    key = (kind, size, weight)
    if key not in _font_cache:
        if kind == 'sans':
            f = ImageFont.truetype(os.path.join(FONTS, 'SpaceGrotesk.ttf'), size)
            try:
                f.set_variation_by_axes([max(300, min(700, weight))])
            except Exception:
                pass
        else:
            name = 'IBMPlexMono-Bold.ttf' if weight >= 600 else 'IBMPlexMono-Regular.ttf'
            f = ImageFont.truetype(os.path.join(FONTS, name), size)
        _font_cache[key] = f
    return _font_cache[key]


def tw(d, s, f):
    return d.textlength(s, font=f)


def fit(d, s, f, max_w):
    if max_w <= 0:
        return ''
    if tw(d, s, f) <= max_w:
        return s
    while s and tw(d, s + '…', f) > max_w:
        s = s[:-1]
    return (s.rstrip() + '…') if s else ''


def wrap(d, words, f, max_w, sep=' · '):
    lines, cur = [], ''
    for w in words:
        cand = w if not cur else cur + sep + w
        if tw(d, cand, f) <= max_w:
            cur = cand
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


# ---------- hjelpere ----------
COUNTRY_NB = {
    'Italy': 'Italia', 'Iceland': 'Island', 'Greece': 'Hellas', 'Philippines': 'Filippinene',
    'Russia': 'Russland', 'Turkey': 'Tyrkia', 'Türkiye': 'Tyrkia', 'Papua New Guinea': 'Papua Ny-Guinea',
    'United States': 'USA', 'Norway': 'Norge', 'Sweden': 'Sverige', 'Denmark': 'Danmark',
    'Svalbard and Jan Mayen': 'Svalbard', 'Ethiopia': 'Etiopia', 'DR Congo': 'Kongo', 'Congo, DRC': 'Kongo',
    'Solomon Islands': 'Salomonøyene', 'France': 'Frankrike', 'Spain': 'Spania', 'China': 'Kina',
    'Norwegian Sea': 'Norskehavet', 'North Sea': 'Nordsjøen', 'Greenland Sea': 'Grønlandshavet',
    'Mid-Atlantic Ridge': 'Midtatlanterhavsryggen', 'Comoros': 'Komorene', 'Reunion': 'Réunion',
    'Kermadec Islands': 'Kermadecøyene', 'Kuril Islands': 'Kurilene', 'Antarctica': 'Antarktis',
}


def nb(s):
    s = s.strip()
    for k, v in COUNTRY_NB.items():
        if s.lower() == k.lower():
            return v
    return s


def short_place(place):
    """'112 km NE of Neiafu, Tonga' -> 'Tonga'; 'Fiji region' -> 'Fiji region'"""
    if not place:
        return 'ukjent'
    if ',' in place:
        return nb(place.split(',')[-1])
    m = re.search(r'\bof\s+(.+)$', place)
    return nb(m.group(1) if m else place)


def norm(name):
    s = unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode()
    return re.sub(r'[^a-z0-9]', '', s.lower())


def km(lat1, lon1, lat2, lon2):
    p = math.pi / 180
    a = (math.sin((lat2 - lat1) * p / 2) ** 2 +
         math.cos(lat1 * p) * math.cos(lat2 * p) * math.sin((lon2 - lon1) * p / 2) ** 2)
    return 12742 * math.asin(math.sqrt(a))


def comma(x, nd=1):
    return f'{x:.{nd}f}'.replace('.', ',')


def thin(n):
    return f'{n:,}'.replace(',', ' ')


def fetch(url):
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


# ---------- kart ----------
MAP_ASPECT = 728 / 1872


def map_size(w):
    return w, round(w * MAP_ASPECT)


def base_map(w, bg, dot):
    w, h = map_size(w)
    img = Image.new('L', (w * SS, h * SS), bg)
    d = ImageDraw.Draw(img)
    step = (10 if w >= 1600 else 9) * SS
    r = (2.1 if w >= 1600 else 1.9) * SS
    y = step / 2
    while y < h * SS:
        lat = LAT0 - (LAT0 - LAT1) * y / (h * SS)
        x = step / 2
        while x < w * SS:
            lon = ((LON0 + 360 * x / (w * SS) + 180) % 360) - 180
            if globe.is_land(lat, lon):
                d.ellipse([x - r, y - r, x + r, y + r], fill=dot)
            x += step
        y += step
    return img, d, w, h


def proj(lat, lon, w, h):
    """-> supersamplede koordinater"""
    return ((lon - LON0) % 360) / 360 * w * SS, (LAT0 - lat) / (LAT0 - LAT1) * h * SS


def quake_map(qs, width):
    """-> (kartbilde, liste med (x, y, ytterradius, skjelv) i kartets piksler)"""
    img, d, w, h = base_map(width, 255, gray(7))
    s = max(0.62, w / 1872)
    marks = []
    for q in sorted(qs, key=lambda q: q['mag']):
        cx, cy = proj(q['lat'], q['lon'], w, h)
        mag = q['mag']
        base = (1.8 + max(mag - 2.5, 0) ** 1.5 * 2.2) * 2 * SS * s
        if mag < 4:
            rings = [(1.0, 0, 1.8)]
        elif mag < 4.5:
            rings = [(1.0, 0, 2.0), (1.7, gray(7), 1.3)]
        else:
            rings = [(1.0, 0, 2.2), (1.7, gray(9), 1.5), (2.4, gray(5), 1.1)]
        if mag >= 5.5:
            rings.append((3.1, gray(3), 1.0))
        for k, lvl, wd in rings:
            r = base * k
            for ox in (-w * SS, 0, w * SS):
                d.ellipse([cx + ox - r, cy - r, cx + ox + r, cy + r], outline=lvl,
                          width=max(1, int(wd * 2 * SS * max(s, 0.8))))
        cr = (1.6 if mag < 4 else 2.4) * 2 * SS * max(s, 0.8)
        d.ellipse([cx - cr, cy - cr, cx + cr, cy + cr], fill=0)
        marks.append((cx / SS, cy / SS, base * rings[-1][0] / SS, q))
    return img.resize((w, h), Image.LANCZOS), marks


def volcano_map(vs, width, bg, max_labels=99):
    """-> (kartbilde, liste med (x, y, størrelse, vulkan, ny?) i kartets piksler)"""
    img, d, w, h = base_map(width, bg, gray(9))
    k = 2 * SS * max(0.7, w / 1872)

    def tri(X, Y, s, fill=None, outline=None, width=1):
        d.polygon([(X, Y - s), (X + s * 0.95, Y + s * 0.62), (X - s * 0.95, Y + s * 0.62)],
                  fill=fill, outline=outline, width=width)

    new = [v for v in vs if v['status'] == 'new']
    ongoing = [v for v in vs if v['status'] != 'new']
    marks = []
    for v in ongoing:
        X, Y = proj(v['lat'], v['lon'], w, h)
        tri(X, Y, 5.2 * k, fill=bg, outline=gray(1), width=max(2, int(1.6 * k)))
        marks.append((X / SS, Y / SS, 5.2 * k / SS, v, False))
    for v in new[:max_labels]:
        X, Y = proj(v['lat'], v['lon'], w, h)
        tri(X, Y, 8.5 * k, fill=255)
        for dx, dy, r, lvl in [(2, -13, 3.0, 1), (6, -20, 2.4, 4), (11, -26, 1.9, 7), (17, -30, 1.4, 9)]:
            d.ellipse([X + dx * k - r * k, Y + dy * k - r * k, X + dx * k + r * k, Y + dy * k + r * k], fill=gray(lvl))
        marks.append((X / SS, Y / SS, 8.5 * k / SS, v, True))
    return img.resize((w, h), Image.LANCZOS), marks


# ---------- etiketter på kartet ----------
def _hit(a, b):
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


def place_labels(d, ox, oy, mw, mh, cands, bg, avoid=()):
    """
    Grådig etikettplassering uten overlapp.
    cands: liste (x, y, r, deler, maks?) i kartets piksler, sortert etter viktighet.
           deler = [(tekst, font, farge), ...] som tegnes etter hverandre på én linje.
    """
    placed = list(avoid)
    points = [(c[0], c[1]) for c in cands]
    for x, y, r, parts, _ in cands:
        widths = [tw(d, t, f) for t, f, _ in parts]
        gap = 7
        lw = sum(widths) + gap * (len(parts) - 1)
        lh = max(f.size for _, f, _ in parts)
        pad = 6
        options = [
            (x + r + pad, y - lh / 2),             # høyre
            (x - r - pad - lw, y - lh / 2),        # venstre
            (x + r * 0.5, y + r + 2),              # under, høyre
            (x - lw - r * 0.5, y + r + 2),         # under, venstre
            (x + r * 0.5, y - r - lh - 2),         # over, høyre
            (x - lw - r * 0.5, y - r - lh - 2),    # over, venstre
        ]
        for lx, ly in options:
            box = (lx - 3, ly - 3, lx + lw + 3, ly + lh + 3)
            if box[0] < 4 or box[1] < 4 or box[2] > mw - 4 or box[3] > mh - 4:
                continue
            if any(_hit(box, b) for b in placed):
                continue
            if any(box[0] < px < box[2] and box[1] < py < box[3] for px, py in points):
                continue
            placed.append(box)
            cx = ox + lx
            for (t, f, col), wdt in zip(parts, widths):
                d.text((cx, oy + ly + lh), t, font=f, fill=col, anchor='ls', stroke_width=4, stroke_fill=bg)
                cx += wdt + gap
            break


def quake_labels(d, ox, oy, m, marks, qs, size, fg=0, sub=None):
    sub = gray(11) if sub is None else sub
    near = min(qs, key=lambda q: km(HOME_LAT, HOME_LON, q['lat'], q['lon'])) if qs else None
    order = sorted(marks, key=lambda t: (t[3] is not near, -t[3]['mag']))
    cands = []
    for i, (x, y, r, q) in enumerate(order):
        big = q['mag'] >= 5.5
        cands.append((x, y, r, [(comma(q['mag']), font('sans', size + (4 if big else 0), 700), fg),
                                (short_place(q['place']), font('sans', size - 2 + (4 if big else 0), 400), sub)], None))
    place_labels(d, ox, oy, m.width, m.height, cands, 255)


def volcano_labels(d, ox, oy, m, marks, size, bg, fg, sub, max_ongoing=99):
    new = [t for t in marks if t[4]]
    old = [t for t in marks if not t[4]][:max_ongoing]
    cands = []
    for x, y, s, v, _ in new:
        cands.append((x, y + s * 0.2, s, [(v['name'], font('sans', size + 2, 700), fg)], None))
    for x, y, s, v, _ in old:
        cands.append((x, y, s, [(v['name'], font('sans', size - 4, 400), sub)], None))
    # askeskyene skal ikke dekkes av tekst
    avoid = [(x - 2, y - s * 3.8, x + s * 2.4, y - s * 0.8) for x, y, s, v, _ in new]
    place_labels(d, ox, oy, m.width, m.height, cands, bg, avoid)


# ---------- felles tegneelementer ----------
def header(d, x, base, title, subtitle, fg, sub, size=60):
    ft = font('sans', size, 700)
    d.text((x, base), title, font=ft, fill=fg, anchor='ls')
    if subtitle:
        d.text((x + tw(d, title, ft) + 26, base), subtitle, font=font('sans', round(size * 0.57), 400), fill=sub, anchor='ls')


def stat(d, x, y, big, caption, fg, sub, max_w, big_size=164, cap_size=34, icon=None):
    d.text((x, y), big, font=font('sans', big_size, 700), fill=fg, anchor='lt')
    cy = y + round(big_size * 1.2)
    cx = x
    if icon:
        icon(d, x, cy + 4)
        cx = x + 42
    d.text((cx, cy), fit(d, caption, font('sans', cap_size, 400), max_w - (cx - x)),
           font=font('sans', cap_size, 400), fill=sub, anchor='lt')


def footer(d, W, H, fg, sub, icon, title, subtitle, right):
    y0 = H - 36 - 92
    d.rectangle([40, y0, W - 40, y0 + 3], fill=fg)
    cy = y0 + 50
    icon(d, 44, cy - 22)
    d.text((108, cy), title, font=font('sans', 36, 700), fill=fg, anchor='lm')
    d.text((108 + tw(d, title, font('sans', 36, 700)) + 24, cy), subtitle, font=font('sans', 32, 400), fill=sub, anchor='lm')
    d.text((W - 44, cy), right, font=font('mono', 30, 400), fill=sub, anchor='rm')


def vline(d, x, y0, y1, fg):
    d.rectangle([x, y0, x + 3, y1], fill=fg)


def hline(d, x0, x1, y, fg):
    d.rectangle([x0, y, x1, y + 3], fill=fg)


# ---------- jordskjelv: data ----------
def load_quakes(sample):
    if sample:
        rows = [(6.1, '112 km NE of Neiafu, Tonga', -20.5, -174.3, 3.2), (5.4, 'Hokkaido, Japan', 42.4, 143.1, 9.7),
                (5.2, 'southern Sumatra, Indonesia', -1.2, 99.4, 22.1), (4.9, 'Antofagasta, Chile', -21.6, -68.9, 1.0),
                (4.8, 'Andreanof Islands, Aleutian Islands, Alaska', 51.6, -176.4, 5.5),
                (4.6, 'Hindu Kush, Afghanistan', 36.5, 70.9, 14.0), (4.5, 'Oaxaca, Mexico', 16.2, -97.9, 18.0),
                (4.4, 'Crete, Greece', 34.9, 25.6, 7.0), (3.6, 'Reykjanes Ridge', 63.9, -22.5, 4.0),
                (3.2, 'North Sea', 60.8, 3.1, 11.9), (2.9, 'Alaska', 61.2, -150.1, 2.0),
                (2.7, 'Central California', 36.1, -120.7, 6.0), (2.6, 'Hawaii', 19.3, -155.2, 0.5),
                (2.5, 'Yellowstone, Wyoming', 44.6, -110.6, 8.0)]
        now = dt.datetime(2026, 11, 12, 13, 47, tzinfo=TZ).astimezone(dt.timezone.utc)
        return [{'mag': m, 'place': p, 'lat': la, 'lon': lo, 'time': now - dt.timedelta(hours=hh)}
                for m, p, la, lo, hh in rows]
    data = json.loads(fetch(USGS_URL))
    out = []
    for f in data.get('features', []):
        pr, g = f.get('properties', {}), f.get('geometry', {})
        if pr.get('mag') is None or not g:
            continue
        lon, lat = g['coordinates'][0], g['coordinates'][1]
        out.append({'mag': float(pr['mag']), 'place': pr.get('place') or '', 'lat': lat, 'lon': lon,
                    'time': dt.datetime.fromtimestamp(pr['time'] / 1000, dt.timezone.utc)})
    return out


def quake_summary(qs):
    if not qs:
        return None
    big = max(qs, key=lambda q: q['mag'])
    near = min(qs, key=lambda q: km(HOME_LAT, HOME_LON, q['lat'], q['lon']))
    dist = km(HOME_LAT, HOME_LON, near['lat'], near['lon'])
    return {
        'big': big, 'near': near, 'dist': dist, 'n': len(qs),
        'latest': max(q['time'] for q in qs).astimezone(TZ),
        'big_cap': f"største · {short_place(big['place'])}, {big['time'].astimezone(TZ):%H:%M}",
        'near_cap': f"nærmest deg · {thin(round(dist / 10) * 10)} km",
    }


def quake_icon(d, x, y, s=44):
    c = (x + s / 2, y + s / 2)
    d.ellipse([c[0] - 5, c[1] - 5, c[0] + 5, c[1] + 5], fill=0)
    d.ellipse([c[0] - 12, c[1] - 12, c[0] + 12, c[1] + 12], outline=0, width=4)
    d.ellipse([c[0] - 20, c[1] - 20, c[0] + 20, c[1] + 20], outline=0, width=2)


# ---------- jordskjelv: layouter ----------
def render_quakes(qs, layout):
    W, H = LAYOUTS[layout]
    img = Image.new('L', (W, H), 255)
    d = ImageDraw.Draw(img)
    S = quake_summary(qs)
    FG, SUB = 0, gray(10)
    big = lambda: comma(S['big']['mag']) if S else '–'

    def map_at(width, x, y, label_size):
        m, marks = quake_map(qs, width)
        img.paste(m, (x, y))
        quake_labels(d, x, y, m, marks, qs, label_size)
        return m

    if layout == 'full':
        header(d, 64, 104, 'Jordskjelv', 'siste 24 timer', FG, SUB)
        m = map_at(W, 0, 130, 26)
        y = 130 + m.height + 56
        colw = (W - 128) / 3
        cols = [(big(), S['big_cap'] if S else 'ingen data'), (str(S['n'] if S else 0), 'skjelv over M2,5'),
                (comma(S['near']['mag']) if S else '–', S['near_cap'] if S else '')]
        for i, (b, cap) in enumerate(cols):
            x = 64 + i * colw + (48 if i else 0)
            if i:
                vline(d, 64 + i * colw, y + 16, y + 236, FG)
            stat(d, x, y, b, cap, FG, SUB, colw - 64)
        footer(d, W, H, FG, SUB, quake_icon, 'Jordas puls', 'USGS · én ring per styrke',
               f"siste {S['latest']:%H:%M}" if S else '')

    elif layout == 'half_horizontal':
        header(d, 40, 66, 'Jordskjelv', 'siste 24 timer', FG, SUB, size=46)
        m = map_at(1500, 0, 88, 22)
        d.text((40, H - 22), f"USGS · siste skjelv {S['latest']:%H:%M}" if S else 'USGS',
               font=font('sans', 24, 400), fill=SUB, anchor='ls')
        vline(d, 1516, 36, H - 36, FG)
        x0, cw = 1548, W - 1548 - 32
        rows = [(big(), short_place(S['big']['place']) if S else 'ingen data'),
                (str(S['n'] if S else 0), 'skjelv over M2,5'),
                (comma(S['near']['mag']) if S else '–', S['near_cap'].replace('nærmest deg · ', 'nærmest · ') if S else '')]
        for i, (b, cap) in enumerate(rows):
            stat(d, x0, 30 + i * 220, b, cap, FG, SUB, cw, big_size=112, cap_size=28)

    elif layout == 'half_vertical':
        header(d, 44, 84, 'Jordskjelv', 'siste 24 t', FG, SUB, size=52)
        m = map_at(W, 0, 110, 21)
        y = 110 + m.height + 44
        stat(d, 44, y, big(), short_place(S['big']['place']) if S else 'ingen data', FG, SUB, 400, big_size=140, cap_size=30)
        vline(d, 468, y + 14, y + 206, FG)
        stat(d, 508, y, str(S['n'] if S else 0), 'skjelv over M2,5', FG, SUB, 380, big_size=140, cap_size=30)
        y += 256
        hline(d, 44, W - 44, y, FG)
        d.text((44, y + 30), 'STØRST SISTE DØGN', font=font('sans', 24, 700), fill=SUB, anchor='lt')
        y += 80
        for q in sorted(qs, key=lambda q: -q['mag'])[:7]:
            d.text((44, y), comma(q['mag']), font=font('sans', 42, 700), fill=FG, anchor='lt')
            tf = font('mono', 28, 400)
            t = f"{q['time'].astimezone(TZ):%H:%M}"
            d.text((W - 44, y + 10), t, font=tf, fill=SUB, anchor='rt')
            pf = font('sans', 34, 400)
            d.text((150, y + 6), fit(d, short_place(q['place']), pf, W - 44 - tw(d, t, tf) - 24 - 150),
                   font=pf, fill=FG, anchor='lt')
            y += 68
        if S:
            d.text((44, H - 32), S['near_cap'].capitalize() + f" · M{comma(S['near']['mag'])}",
                   font=font('sans', 26, 400), fill=SUB, anchor='ls')

    elif layout == 'quadrant':
        header(d, 36, 62, 'Jordskjelv', 'siste 24 t', FG, SUB, size=42)
        m = map_at(W, 0, 84, 20)
        y = 84 + m.height + 34
        stat(d, 36, y, big(), short_place(S['big']['place']) if S else 'ingen data', FG, SUB, 400, big_size=118, cap_size=28)
        vline(d, 460, y + 12, y + 176, FG)
        stat(d, 496, y, str(S['n'] if S else 0), 'skjelv over M2,5', FG, SUB, 400, big_size=118, cap_size=28)

    return quantize16(img)


# ---------- vulkaner: data ----------
SAMPLE_VOLC = [('Etna', 'Italy', 'new'), ('Kanlaon', 'Philippines', 'new'), ('Lewotobi', 'Indonesia', 'new'),
               ('Reykjanes', 'Iceland', 'new')] + [(n, '', 'ongoing') for n in (
    'Kilauea', 'Stromboli', 'Sakurajima', 'Suwanosejima', 'Semeru', 'Merapi', 'Dukono', 'Ibu', 'Popocatepetl',
    'Fuego', 'Santa Maria', 'Sangay', 'Reventador', 'Sabancaya', 'Villarrica', 'Klyuchevskoy', 'Sheveluch',
    'Ebeko', 'Great Sitkin', 'Nyiragongo', 'Marapi')]


def load_volcanoes(sample, dump=False):
    table = {norm(k): v for k, v in json.load(open(os.path.join(HERE, 'volcanoes.json'))).items()
             if not k.startswith('_')}
    if sample:
        out = []
        for n, c, s in SAMPLE_VOLC:
            la, lo = table[norm(n)]
            out.append({'name': n, 'country': c, 'status': s, 'lat': la, 'lon': lo})
        return out, dt.date(2026, 11, 12)

    root = ET.fromstring(fetch(GVP_URL))
    items, week_date = [], None
    for it in root.iter():
        if not it.tag.endswith('item'):
            continue
        get = lambda tag: next((c.text or '' for c in it if c.tag.split('}')[-1] == tag), '')
        title, desc = get('title'), get('description')
        pt = next((c.text for c in it if c.tag.split('}')[-1] == 'point'), None)
        m = re.match(r'\s*(.+?)\s*\(([^)]+)\)', title)
        name, country = (m.group(1), m.group(2)) if m else (title.split(' - ')[0].strip(), '')
        blob = (title + ' ' + desc).lower()
        status = 'new' if re.search(r'new activity|\bnew\b\s*$|\(new\)|- new\b', blob) else 'ongoing'
        lat = lon = None
        if pt:
            try:
                lat, lon = map(float, pt.split()[:2])
            except ValueError:
                pass
        if lat is None and norm(name) in table:
            lat, lon = table[norm(name)]
        pub = get('pubDate')
        if pub and week_date is None:
            try:
                week_date = dt.datetime.strptime(pub[:16], '%a, %d %b %Y').date()
            except ValueError:
                pass
        rec = {'name': name, 'country': country, 'status': status, 'lat': lat, 'lon': lon}
        if dump:
            print('  ', rec, file=sys.stderr)
        if lat is None:
            print(f'  ! mangler koordinater for «{name}» – legg den til i volcanoes.json', file=sys.stderr)
            continue
        items.append(rec)
    uniq = {}
    for v in items:
        k = norm(v['name'])
        if k not in uniq or v['status'] == 'new':
            uniq[k] = v
    return list(uniq.values()), week_date or dt.date.today()


# ---------- vulkaner: layouter ----------
def render_volcanoes(vs, week_date, layout):
    W, H = LAYOUTS[layout]
    BG, FG, SUB = gray(14), 255, gray(5)
    img = Image.new('L', (W, H), BG)
    d = ImageDraw.Draw(img)
    new = [v for v in vs if v['status'] == 'new']
    ongoing = [v for v in vs if v['status'] != 'new']
    week = week_date.isocalendar()[1]

    def tri_icon(filled):
        def f(d, x, y):
            pts = [(x + 14, y), (x + 28, y + 24), (x, y + 24)]
            d.polygon(pts, fill=FG) if filled else d.polygon(pts, outline=FG, width=3)
        return f

    def map_at(width, x, y, label_size, max_ongoing=99):
        m, marks = volcano_map(vs, width, BG)
        img.paste(m, (x, y))
        volcano_labels(d, x, y, m, marks, label_size, BG, FG, SUB, max_ongoing)
        return m

    def name_row(x, y, v, max_w, name_size=46, cty_size=30):
        fn = font('sans', name_size, 700)
        nm = fit(d, v['name'], fn, max_w)
        d.text((x, y), nm, font=fn, fill=FG, anchor='lt')
        cx = x + tw(d, nm, fn) + 14
        ct = fit(d, nb(v['country']), font('sans', cty_size, 400), x + max_w - cx)
        if ct and ct != '…':
            d.text((cx, y + round(name_size * 0.22)), ct, font=font('sans', cty_size, 400), fill=SUB, anchor='lt')

    if layout == 'full':
        header(d, 64, 104, 'Vulkaner', 'aktive denne uka', FG, SUB)
        m = map_at(W, 0, 130, 26)
        y = 130 + m.height + 56
        stat(d, 64, y, str(len(new)), 'nye utbrudd', FG, SUB, 300, icon=tri_icon(True))
        stat(d, 394, y, str(len(ongoing)), 'pågående', FG, SUB, 300, icon=tri_icon(False))
        lx = 716
        vline(d, lx, y + 16, y + 236, FG)
        gx, colw = lx + 56, (W - 64 - (lx + 56)) / 2
        if not new:
            d.text((gx, y + 30), 'Ingen nye utbrudd denne uka', font=font('sans', 40, 700), fill=FG, anchor='lt')
        for i, v in enumerate(new[:4]):
            name_row(gx + (i % 2) * colw, y + 30 + (i // 2) * 96, v, colw - 20)
        if len(new) > 4:
            d.text((gx, y + 206), f'+ {len(new) - 4} til', font=font('sans', 30, 400), fill=SUB, anchor='lt')

        def icon(d, x, y):
            d.polygon([(x + 22, y + 14), (x + 42, y + 44), (x + 2, y + 44)], fill=FG)
            d.ellipse([x + 22, y + 2, x + 30, y + 10], fill=FG)
            d.ellipse([x + 32, y - 2, x + 37, y + 3], fill=SUB)
        footer(d, W, H, FG, SUB, icon, 'Vulkaner', 'Smithsonian GVP · ukesrapport', f'uke {week}')

    elif layout == 'half_horizontal':
        header(d, 40, 66, 'Vulkaner', 'aktive denne uka', FG, SUB, size=46)
        m = map_at(1500, 0, 88, 22)
        d.text((40, H - 22), f'Smithsonian GVP · uke {week}', font=font('sans', 24, 400), fill=SUB, anchor='ls')
        vline(d, 1516, 36, H - 36, FG)
        x0, cw = 1548, W - 1548 - 32
        stat(d, x0, 30, str(len(new)), 'nye utbrudd', FG, SUB, cw, big_size=112, cap_size=28, icon=tri_icon(True))
        stat(d, x0, 250, str(len(ongoing)), 'pågående', FG, SUB, cw, big_size=112, cap_size=28, icon=tri_icon(False))
        hline(d, x0, W - 32, 474, FG)
        f = font('sans', 28, 400)
        lines = wrap(d, [v['name'] for v in new], font('sans', 30, 700), cw, sep=', ') or ['Ingen nye']
        yy = 500
        for line in lines[:4]:
            d.text((x0, yy), line, font=font('sans', 30, 700), fill=FG, anchor='lt')
            yy += 40

    elif layout == 'half_vertical':
        header(d, 44, 84, 'Vulkaner', 'denne uka', FG, SUB, size=52)
        m = map_at(W, 0, 110, 21, max_ongoing=10)
        y = 110 + m.height + 44
        stat(d, 44, y, str(len(new)), 'nye utbrudd', FG, SUB, 400, big_size=140, cap_size=30, icon=tri_icon(True))
        vline(d, 468, y + 14, y + 206, FG)
        stat(d, 508, y, str(len(ongoing)), 'pågående', FG, SUB, 380, big_size=140, cap_size=30, icon=tri_icon(False))
        y += 256
        hline(d, 44, W - 44, y, FG)
        y += 36
        if not new:
            d.text((44, y), 'Ingen nye utbrudd', font=font('sans', 40, 700), fill=FG, anchor='lt')
            y += 76
        for v in new[:6]:
            name_row(44, y, v, W - 88, name_size=42, cty_size=28)
            y += 70
        if ongoing and y < H - 200:
            y += 18
            d.text((44, y), 'PÅGÅENDE', font=font('sans', 24, 700), fill=SUB, anchor='lt')
            y += 46
            f = font('sans', 30, 400)
            for line in wrap(d, [v['name'] for v in ongoing], f, W - 88):
                if y > H - 56:
                    break
                d.text((44, y), line, font=f, fill=SUB, anchor='lt')
                y += 44

    elif layout == 'quadrant':
        header(d, 36, 62, 'Vulkaner', f'uke {week}', FG, SUB, size=42)
        m = map_at(W, 0, 84, 20, max_ongoing=6)
        y = 84 + m.height + 34
        stat(d, 36, y, str(len(new)), 'nye utbrudd', FG, SUB, 400, big_size=118, cap_size=28, icon=tri_icon(True))
        vline(d, 460, y + 12, y + 176, FG)
        stat(d, 496, y, str(len(ongoing)), 'pågående', FG, SUB, 400, big_size=118, cap_size=28, icon=tri_icon(False))

    return quantize16(img)


# ---------- main ----------
def save_all(kind, render, out):
    digest = hashlib.sha1()
    for layout in LAYOUTS:
        im = render(layout)
        digest.update(im.tobytes())
        p = os.path.join(out, f'{kind}_{layout}.png')
        im.save(p, optimize=True)
        if layout == 'full':
            shutil.copyfile(p, os.path.join(out, f'{kind}.png'))   # bakoverkompatibel URL
    return digest.hexdigest()[:12]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--sample', action='store_true', help='bruk eksempeldata')
    ap.add_argument('--dump', action='store_true', help='skriv ut tolkede data')
    ap.add_argument('--out', default=os.path.join(HERE, 'site'))
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    status, ok = {}, True
    try:
        qs = load_quakes(a.sample)
        if a.dump:
            for q in sorted(qs, key=lambda q: -q['mag'])[:10]:
                print('  ', q['mag'], q['place'], file=sys.stderr)
        status['quakes_v'] = save_all('quakes', lambda L: render_quakes(qs, L), a.out)
        status['quakes_count'] = len(qs)
        print(f'quakes: {len(qs)} skjelv')
    except Exception as e:
        ok = False
        print(f'Jordskjelv feilet: {e!r}', file=sys.stderr)
    try:
        vs, wk = load_volcanoes(a.sample, a.dump)
        status['volcanoes_v'] = save_all('volcanoes', lambda L: render_volcanoes(vs, wk, L), a.out)
        status['volcanoes_new'] = sum(v['status'] == 'new' for v in vs)
        status['volcanoes_ongoing'] = sum(v['status'] != 'new' for v in vs)
        print(f"volcanoes: {status['volcanoes_new']} nye, {status['volcanoes_ongoing']} pågående")
    except Exception as e:
        ok = False
        print(f'Vulkaner feilet: {e!r}', file=sys.stderr)

    with open(os.path.join(a.out, 'status.json'), 'w') as f:
        json.dump(status, f, ensure_ascii=False)
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
