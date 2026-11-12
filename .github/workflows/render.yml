#!/usr/bin/env python3
"""
Tegner to TRMNL X-skjermer (1872x1404, 16 gråtoner):
  quakes.png      – jordskjelv siste døgn (USGS, M2.5+)
  volcanoes.png   – vulkaner denne uka (Smithsonian/USGS Weekly Volcanic Activity Report)

Bruk:
  python render.py                 # henter ferske data, skriver til ./site/
  python render.py --sample        # bruker innebygde eksempeldata (ingen nett)
  python render.py --dump          # skriver også ut det som ble tolket fra feedene
  python render.py --out mappe     # annen utmappe

Miljøvariabler (valgfrie):
  HOME_LAT, HOME_LON              – din posisjon, brukes for «nærmest deg» (standard Oslo)
  TZ_NAME                         – tidssone for klokkeslett (standard Europe/Oslo)
"""
import argparse, datetime as dt, json, math, os, re, sys, unicodedata, urllib.request
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFont
from global_land_mask import globe

HERE = os.path.dirname(os.path.abspath(__file__))
FONTS = os.path.join(HERE, 'fonts')

USGS_URL = 'https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/2.5_day.geojson'
GVP_URL = 'https://volcano.si.edu/news/WeeklyVolcanoRSS.xml'
UA = 'trmnl-jorda/1.0 (personal e-ink display)'

HOME_LAT = float(os.environ.get('HOME_LAT', '59.91'))
HOME_LON = float(os.environ.get('HOME_LON', '10.75'))
TZ = ZoneInfo(os.environ.get('TZ_NAME', 'Europe/Oslo'))

# ---------- skjerm og kart ----------
W, H = 1872, 1404                 # TRMNL X
MAP_Y, MAP_H = 130, 728           # kartstripen, full bredde
SS = 2                            # supersampling for kartet
LON0, LAT0, LAT1 = -28.0, 82.0, -58.0   # Stillehavet i midten, venstre kant 28°V


def gray(level):
    """level 0 (hvit) .. 15 (svart) -> 8-bit gråverdi"""
    return 255 - level * 17


def quantize16(img):
    return img.point(lambda v: int(round(v / 17.0)) * 17)


# ---------- fonter ----------
_font_cache = {}


def font(kind, size, weight=400):
    key = (kind, size, weight)
    if key in _font_cache:
        return _font_cache[key]
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
    return f


def text_w(d, s, f):
    return d.textlength(s, font=f)


def fit(d, s, f, max_w):
    if text_w(d, s, f) <= max_w:
        return s
    while s and text_w(d, s + '…', f) > max_w:
        s = s[:-1]
    return s.rstrip() + '…'


# ---------- hjelpere ----------
COUNTRY_NB = {
    'Italy': 'Italia', 'Iceland': 'Island', 'Greece': 'Hellas', 'Philippines': 'Filippinene',
    'Russia': 'Russland', 'Turkey': 'Tyrkia', 'Türkiye': 'Tyrkia', 'Papua New Guinea': 'Papua Ny-Guinea',
    'United States': 'USA', 'Ecuador': 'Ecuador', 'Colombia': 'Colombia', 'Peru': 'Peru',
    'Chile': 'Chile', 'Argentina': 'Argentina', 'Mexico': 'Mexico', 'Japan': 'Japan',
    'Indonesia': 'Indonesia', 'Vanuatu': 'Vanuatu', 'Tonga': 'Tonga', 'Fiji': 'Fiji',
    'New Zealand': 'New Zealand', 'Norway': 'Norge', 'Sweden': 'Sverige', 'Denmark': 'Danmark',
    'Svalbard and Jan Mayen': 'Svalbard', 'Ethiopia': 'Etiopia', 'Tanzania': 'Tanzania',
    'DR Congo': 'Kongo', 'Congo, DRC': 'Kongo', 'Guatemala': 'Guatemala', 'Nicaragua': 'Nicaragua',
    'Costa Rica': 'Costa Rica', 'El Salvador': 'El Salvador', 'Solomon Islands': 'Salomonøyene',
    'France': 'Frankrike', 'Spain': 'Spania', 'China': 'Kina', 'Taiwan': 'Taiwan', 'Iran': 'Iran',
    'Afghanistan': 'Afghanistan', 'Pakistan': 'Pakistan', 'India': 'India', 'Nepal': 'Nepal',
    'Alaska': 'Alaska', 'Hawaii': 'Hawaii', 'California': 'California', 'Puerto Rico': 'Puerto Rico',
    'Norwegian Sea': 'Norskehavet', 'North Sea': 'Nordsjøen', 'Greenland Sea': 'Grønlandshavet',
    'Mid-Atlantic Ridge': 'Midtatlanterhavsryggen', 'Comoros': 'Komorene', 'Reunion': 'Réunion',
    'Bolivia': 'Bolivia', 'Kermadec Islands': 'Kermadecøyene', 'Kuril Islands': 'Kurilene',
}


def nb(s):
    s = s.strip()
    for k, v in COUNTRY_NB.items():
        if s.lower() == k.lower() or s.lower().endswith(' ' + k.lower()):
            return s[: len(s) - len(k)] + v if s.lower() != k.lower() else v
    return s


def short_place(place):
    """'112 km NE of Nuku‘alofa, Tonga' -> 'Tonga'; 'Fiji region' -> 'Fiji region'"""
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
def xy(lat, lon, w=W, h=MAP_H):
    return ((lon - LON0) % 360) / 360 * w, (LAT0 - lat) / (LAT0 - LAT1) * h


def base_map(bg, dot):
    Ws, Hs = W * SS, MAP_H * SS
    img = Image.new('L', (Ws, Hs), bg)
    d = ImageDraw.Draw(img)
    step, r = 10 * SS, 2.1 * SS
    y = step / 2
    while y < Hs:
        lat = LAT0 - (LAT0 - LAT1) * y / Hs
        x = step / 2
        while x < Ws:
            lon = ((LON0 + 360 * x / Ws + 180) % 360) - 180
            if globe.is_land(lat, lon):
                d.ellipse([x - r, y - r, x + r, y + r], fill=dot)
            x += step
        y += step
    return img, d


def footer(d, fg, sub, icon, title, subtitle, right):
    y0 = H - 36 - 92
    d.rectangle([40, y0, W - 40, y0 + 3], fill=fg)
    cy = y0 + 50
    icon(d, 44, cy - 22, 44)
    d.text((108, cy), title, font=font('sans', 36, 700), fill=fg, anchor='lm')
    tw = text_w(d, title, font('sans', 36, 700))
    d.text((108 + tw + 24, cy), subtitle, font=font('sans', 32, 400), fill=sub, anchor='lm')
    d.text((W - 44, cy), right, font=font('mono', 30, 400), fill=sub, anchor='rm')


def header(d, fg, sub, title, subtitle):
    ft = font('sans', 60, 700)
    d.text((64, 104), title, font=ft, fill=fg, anchor='ls')
    d.text((64 + text_w(d, title, ft) + 28, 104), subtitle, font=font('sans', 34, 400), fill=sub, anchor='ls')


BIG = ('sans', 164, 700)


def stat(d, x, y, big, caption, fg, sub, max_w):
    d.text((x, y), big, font=font(*BIG), fill=fg, anchor='lt')
    d.text((x, y + 196), fit(d, caption, font('sans', 34, 400), max_w), font=font('sans', 34, 400), fill=sub, anchor='lt')


# ---------- jordskjelv ----------
def load_quakes(sample):
    if sample:
        rows = [(6.1, '112 km NE of Neiafu, Tonga', -20.5, -174.3, 3.2), (5.4, 'Hokkaido, Japan', 42.4, 143.1, 9.7),
                (5.2, 'southern Sumatra, Indonesia', -1.2, 99.4, 22.1), (4.9, 'Antofagasta, Chile', -21.6, -68.9, 1.0),
                (4.8, 'Andreanof Islands, Aleutian Islands, Alaska', 51.6, -176.4, 5.5), (4.6, 'Hindu Kush, Afghanistan', 36.5, 70.9, 14.0),
                (4.5, 'Oaxaca, Mexico', 16.2, -97.9, 18.0), (4.4, 'Crete, Greece', 34.9, 25.6, 7.0),
                (3.6, 'Reykjanes Ridge', 63.9, -22.5, 4.0), (3.2, 'North Sea', 60.8, 3.1, 11.9),
                (2.9, 'Alaska', 61.2, -150.1, 2.0), (2.7, 'Central California', 36.1, -120.7, 6.0),
                (2.6, 'Hawaii', 19.3, -155.2, 0.5), (2.5, 'Yellowstone, Wyoming', 44.6, -110.6, 8.0)]
        now = dt.datetime.now(dt.timezone.utc)
        return [{'mag': m, 'place': p, 'lat': la, 'lon': lo, 'time': now - dt.timedelta(hours=h)} for m, p, la, lo, h in rows]
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


def render_quakes(qs, path):
    img = Image.new('L', (W, H), 255)
    d = ImageDraw.Draw(img)
    header(d, 0, gray(10), 'Jordskjelv', 'siste 24 timer')

    m, md = base_map(255, gray(7))
    big_label = None
    for q in sorted(qs, key=lambda q: q['mag']):
        cx, cy = xy(q['lat'], q['lon'], W * SS, MAP_H * SS)
        mag = q['mag']
        base = (1.8 + max(mag - 2.5, 0) ** 1.5 * 2.2) * 2 * SS
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
            for ox in (-W * SS, 0, W * SS):
                md.ellipse([cx + ox - r, cy - r, cx + ox + r, cy + r], outline=lvl, width=max(1, int(wd * 2 * SS)))
        cr = (1.6 if mag < 4 else 2.4) * 2 * SS
        md.ellipse([cx - cr, cy - cr, cx + cr, cy + cr], fill=0)
        big_label = (cx / SS, cy / SS, base * rings[-1][0] / SS, q)
    img.paste(m.resize((W, MAP_H), Image.LANCZOS), (0, MAP_Y))

    if qs:
        biggest = max(qs, key=lambda q: q['mag'])
        x, y, rr, q = big_label
        lab = f"M{comma(q['mag'])} {short_place(q['place'])}"
        fl = font('sans', 30, 700)
        if x + rr + 14 + text_w(d, lab, fl) < W - 20:
            d.text((x + rr + 14, MAP_Y + y), lab, font=fl, fill=0, anchor='lm')
        else:
            d.text((x - rr - 14, MAP_Y + y), lab, font=fl, fill=0, anchor='rm')
        near = min(qs, key=lambda q: km(HOME_LAT, HOME_LON, q['lat'], q['lon']))
        dist = km(HOME_LAT, HOME_LON, near['lat'], near['lon'])
        latest = max(q['time'] for q in qs).astimezone(TZ)
        cols = [
            (comma(biggest['mag']), f"største · {short_place(biggest['place'])}, {biggest['time'].astimezone(TZ):%H:%M}"),
            (str(len(qs)), 'skjelv over M2,5'),
            (comma(near['mag']), f"nærmest deg · {thin(round(dist / 10) * 10)} km"),
        ]
        right = f'siste {latest:%H:%M}'
    else:
        cols = [('–', 'ingen data'), ('0', 'skjelv over M2,5'), ('–', '')]
        right = ''

    top = MAP_Y + MAP_H + 56
    colw = (W - 128) / 3
    for i, (big, cap) in enumerate(cols):
        x = 64 + i * colw + (48 if i else 0)
        if i:
            d.rectangle([64 + i * colw, top + 16, 64 + i * colw + 3, top + 236], fill=0)
        stat(d, x, top, big, cap, 0, gray(10), colw - 64)

    def icon(d, x, y, s):
        c = (x + s / 2, y + s / 2)
        d.ellipse([c[0] - 5, c[1] - 5, c[0] + 5, c[1] + 5], fill=0)
        d.ellipse([c[0] - 12, c[1] - 12, c[0] + 12, c[1] + 12], outline=0, width=4)
        d.ellipse([c[0] - 20, c[1] - 20, c[0] + 20, c[1] + 20], outline=0, width=2)

    footer(d, 0, gray(10), icon, 'Jordas puls', 'USGS · én ring per styrke', right)
    quantize16(img).save(path, optimize=True)


# ---------- vulkaner ----------
SAMPLE_VOLC = [('Etna', 'Italy', 'new'), ('Kanlaon', 'Philippines', 'new'), ('Lewotobi', 'Indonesia', 'new'),
               ('Reykjanes', 'Iceland', 'new')] + [(n, '', 'ongoing') for n in (
    'Kilauea', 'Stromboli', 'Sakurajima', 'Suwanosejima', 'Semeru', 'Merapi', 'Dukono', 'Ibu', 'Popocatepetl',
    'Fuego', 'Santa Maria', 'Sangay', 'Reventador', 'Sabancaya', 'Villarrica', 'Klyuchevskoy', 'Sheveluch',
    'Ebeko', 'Great Sitkin', 'Nyiragongo', 'Marapi')]


def load_volcanoes(sample, dump=False):
    table = {norm(k): v for k, v in json.load(open(os.path.join(HERE, 'volcanoes.json'))).items() if not k.startswith('_')}
    if sample:
        out = []
        for n, c, s in SAMPLE_VOLC:
            la, lo = table[norm(n)]
            out.append({'name': n, 'country': c, 'status': s, 'lat': la, 'lon': lo})
        return out, dt.date.today()

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
    # samme vulkan kan stå flere ganger – behold «new» om den finnes
    uniq = {}
    for v in items:
        k = norm(v['name'])
        if k not in uniq or v['status'] == 'new':
            uniq[k] = v
    return list(uniq.values()), week_date or dt.date.today()


def render_volcanoes(vs, week_date, path):
    BG, FG, SUB = gray(14), 255, gray(5)
    img = Image.new('L', (W, H), BG)
    d = ImageDraw.Draw(img)
    header(d, FG, SUB, 'Vulkaner', 'aktive denne uka')

    m, md = base_map(BG, gray(9))
    k = 2 * SS

    def tri(X, Y, s, fill=None, outline=None, width=1):
        md.polygon([(X, Y - s), (X + s * 0.95, Y + s * 0.62), (X - s * 0.95, Y + s * 0.62)],
                   fill=fill, outline=outline, width=width)

    new = [v for v in vs if v['status'] == 'new']
    ongoing = [v for v in vs if v['status'] != 'new']
    for v in ongoing:
        X, Y = xy(v['lat'], v['lon'], W * SS, MAP_H * SS)
        tri(X, Y, 5.2 * k, fill=BG, outline=gray(1), width=int(1.6 * k))
    labels = []
    for i, v in enumerate(new[:9]):
        X, Y = xy(v['lat'], v['lon'], W * SS, MAP_H * SS)
        tri(X, Y, 8.5 * k, fill=255)
        for dx, dy, r, lvl in [(2, -13, 3.0, 1), (6, -20, 2.4, 4), (11, -26, 1.9, 7), (17, -30, 1.4, 9)]:
            md.ellipse([X + dx * k - r * k, Y + dy * k - r * k, X + dx * k + r * k, Y + dy * k + r * k], fill=gray(lvl))
        labels.append((X / SS, Y / SS, i + 1))
    img.paste(m.resize((W, MAP_H), Image.LANCZOS), (0, MAP_Y))
    for x, y, n in labels:
        d.text((x + 22, MAP_Y + y + 4), str(n), font=font('mono', 28, 700), fill=FG, anchor='lm')

    top = MAP_Y + MAP_H + 56

    def small_tri(x, y, filled):
        pts = [(x + 14, y), (x + 28, y + 24), (x, y + 24)]
        if filled:
            d.polygon(pts, fill=FG)
        else:
            d.polygon(pts, outline=FG, width=3)

    for i, (n, cap, filled) in enumerate([(len(new), 'nye utbrudd', True), (len(ongoing), 'pågående', False)]):
        x = 64 + i * 330
        d.text((x, top), str(n), font=font(*BIG), fill=FG, anchor='lt')
        small_tri(x, top + 202, filled)
        d.text((x + 44, top + 196), cap, font=font('sans', 34, 400), fill=SUB, anchor='lt')

    lx = 64 + 2 * 330 - 8
    d.rectangle([lx, top + 16, lx + 3, top + 236], fill=FG)
    gx, colw = lx + 56, (W - 64 - (lx + 56)) / 2
    if not new:
        d.text((gx, top + 30), 'Ingen nye utbrudd denne uka', font=font('sans', 40, 700), fill=FG, anchor='lt')
    for i, v in enumerate(new[:4]):
        x = gx + (i % 2) * colw
        y = top + 30 + (i // 2) * 96
        d.text((x, y + 6), str(i + 1), font=font('mono', 30, 700), fill=FG, anchor='lt')
        fn = font('sans', 46, 700)
        nm = fit(d, v['name'], fn, colw - 60)
        d.text((x + 40, y), nm, font=fn, fill=FG, anchor='lt')
        cx = x + 40 + text_w(d, nm, fn) + 16
        ctry = fit(d, nb(v['country']), font('sans', 30, 400), max(0, x + colw - 20 - cx))
        if ctry and ctry != '…':
            d.text((cx, y + 10), ctry, font=font('sans', 30, 400), fill=SUB, anchor='lt')
    if len(new) > 4:
        d.text((gx, top + 206), f'+ {len(new) - 4} til', font=font('sans', 30, 400), fill=SUB, anchor='lt')

    def icon(d, x, y, s):
        d.polygon([(x + 22, y + 14), (x + 42, y + 44), (x + 2, y + 44)], fill=FG)
        d.ellipse([x + 22, y + 2, x + 30, y + 10], fill=FG)
        d.ellipse([x + 32, y - 2, x + 37, y + 3], fill=SUB)

    week = week_date.isocalendar()[1]
    footer(d, FG, SUB, icon, 'Vulkaner', 'Smithsonian GVP · ukesrapport', f'uke {week}')
    quantize16(img).save(path, optimize=True)


# ---------- main ----------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--sample', action='store_true', help='bruk eksempeldata')
    ap.add_argument('--dump', action='store_true', help='skriv ut tolkede data')
    ap.add_argument('--out', default=os.path.join(HERE, 'site'))
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    ok = True
    try:
        qs = load_quakes(a.sample)
        if a.dump:
            for q in sorted(qs, key=lambda q: -q['mag'])[:10]:
                print('  ', q['mag'], q['place'], file=sys.stderr)
        render_quakes(qs, os.path.join(a.out, 'quakes.png'))
        print(f'quakes.png: {len(qs)} skjelv')
    except Exception as e:
        ok = False
        print(f'Jordskjelv feilet: {e}', file=sys.stderr)
    try:
        vs, wk = load_volcanoes(a.sample, a.dump)
        render_volcanoes(vs, wk, os.path.join(a.out, 'volcanoes.png'))
        print(f"volcanoes.png: {sum(v['status'] == 'new' for v in vs)} nye, {sum(v['status'] != 'new' for v in vs)} pågående")
    except Exception as e:
        ok = False
        print(f'Vulkaner feilet: {e}', file=sys.stderr)
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
