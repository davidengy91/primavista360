"""
Guida "radar": disegna la stanza ricostruita nella stessa proiezione del 360 (ray-casting dalla camera).

Per ogni pixel del 360 si calcola la direzione del raggio e che cosa colpisce per primo:
pavimento, soffitto, una delle 4 pareti o un mobile (box o cilindro a misura reale).
Da lì si producono:
- guida_controllo.jpg  : il 360 originale con griglia azzurra a 50 cm sul pavimento, mobili come box
                         semitrasparenti con etichetta e misure, elementi fissi contornati in rosso "NON SPOSTARE";
- guida_pulita.jpg     : la stessa stanza senza foto, scritte né griglia (pareti grigie, fissi e mobili colorati);
- pianta.png           : la pianta vista dall'alto con le misure, per verifica.
"""
import math

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .geometria import _direzioni_equi
from .p3_stanza import TIPI_FISSI, angoli_mobile

COLORI_MOBILI = [(214, 120, 40), (60, 170, 90), (170, 80, 200), (40, 150, 220), (200, 60, 90),
                 (30, 190, 190), (120, 110, 230), (90, 140, 40)]   # BGR


def _font(dimensione):
    for nome in ("C:/Windows/Fonts/segoeuib.ttf", "C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/arial.ttf"):
        try:
            return ImageFont.truetype(nome, dimensione)
        except OSError:
            continue
    return ImageFont.load_default()


def ray_casting(s, larghezza):
    """Calcola per ogni pixel del 360 cosa viene colpito. Restituisce un dizionario di mappe."""
    h_img = larghezza // 2
    dx, dy, dz = _direzioni_equi(larghezza, h_img)
    c, sn = math.cos(s["theta"]), math.sin(s["theta"])
    rx, rz = c * dx + sn * dz, -sn * dx + c * dz          # direzioni nel sistema della stanza
    ry = dy
    inf = np.float32(1e9)
    hcam = s["h"]

    def t_piano(comp, valore):
        with np.errstate(divide="ignore", invalid="ignore"):
            t = np.float32(valore) / comp
        return np.where((t > 0) & np.isfinite(t), t, inf).astype(np.float32)

    candidati = [t_piano(ry, -hcam), t_piano(ry, s["H"] - hcam),
                 t_piano(rx, s["XL"]), t_piano(rx, s["XR"]), t_piano(rz, s["ZB"]), t_piano(rz, s["ZW"])]
    pila = np.stack(candidati)
    superficie = np.argmin(pila, axis=0).astype(np.int8)      # 0 pav, 1 soff, 2 sx, 3 dx, 4 dietro, 5 fondo
    t = np.min(pila, axis=0)
    del pila, candidati

    mobile = np.full(t.shape, -1, np.int16)
    locale = np.zeros(t.shape + (3,), np.float32)              # coordinate del punto colpito nel mobile
    for i, m in enumerate(s["mobili"]):
        cx, cz = m["centro_m"]
        y0 = -hcam + m["quota_m"]
        if m.get("forma") == "cilindro":
            r = m["L"] / 2
            ox, oz = -cx, -cz
            a = rx * rx + rz * rz
            b = 2 * (ox * rx + oz * rz)
            cc = ox * ox + oz * oz - r * r
            disc = b * b - 4 * a * cc
            with np.errstate(invalid="ignore", divide="ignore"):
                t1 = (-b - np.sqrt(np.maximum(disc, 0))) / (2 * a)
            y1 = t1 * ry
            lato = (disc > 0) & (t1 > 0) & (y1 >= y0) & (y1 <= y0 + m["A"])
            with np.errstate(divide="ignore", invalid="ignore"):
                t2 = (y0 + m["A"]) / ry
            px, pz = t2 * rx - cx, t2 * rz - cz
            sopra = (t2 > 0) & (px * px + pz * pz <= r * r)
            tm = np.where(lato, t1, inf)
            tm = np.where(sopra & (t2 < tm), t2, tm)
        else:
            ang = math.radians(m["rot"])
            ca, sa = math.cos(ang), math.sin(ang)
            # assi del mobile: larghezza (ex), profondità (ez)
            ex, ez = (ca, -sa), (sa, ca)
            o = np.array([-cx, -cz])
            ol = (o[0] * ex[0] + o[1] * ex[1], o[0] * ez[0] + o[1] * ez[1])
            dl_x = rx * ex[0] + rz * ex[1]
            dl_z = rx * ez[0] + rz * ez[1]
            half = (m["L"] / 2, m["P"] / 2)
            tmin = np.zeros_like(t)
            tmax = np.full_like(t, inf)
            for o_k, d_k, lo, hi in ((ol[0], dl_x, -half[0], half[0]), (ol[1], dl_z, -half[1], half[1]),
                                     (0.0, ry, y0, y0 + max(m["A"], 0.01))):
                with np.errstate(divide="ignore", invalid="ignore"):
                    ta = (lo - o_k) / d_k
                    tb = (hi - o_k) / d_k
                tmin = np.maximum(tmin, np.minimum(ta, tb))
                tmax = np.minimum(tmax, np.maximum(ta, tb))
            colpito = (tmax >= tmin) & (tmax > 0) & np.isfinite(tmin)
            tm = np.where(colpito, tmin, inf)
        vince = tm < t
        t = np.where(vince, tm, t)
        mobile[vince] = i
        if vince.any():
            px, py, pz = tm[vince] * rx[vince], tm[vince] * ry[vince], tm[vince] * rz[vince]
            if m.get("forma") == "cilindro":
                locale[vince] = np.stack([px - cx, py - y0, pz - cz], axis=-1)
            else:
                lx = (px - cx) * ex[0] + (pz - cz) * ex[1]
                lz = (px - cx) * ez[0] + (pz - cz) * ez[1]
                locale[vince] = np.stack([lx, py - y0, lz], axis=-1)
    punto = np.stack([t * rx, t * ry, t * rz], axis=-1)
    return {"superficie": superficie, "t": t, "mobile": mobile, "locale": locale, "punto": punto,
            "impronta": t * np.float32(2 * math.pi / larghezza)}       # metri coperti da un pixel


def _uv_parete(punto, superficie, hcam):
    u = np.where((superficie == 2) | (superficie == 3), punto[..., 2], punto[..., 0])
    return u, punto[..., 1] + hcam


def _maschere_fissi(s, rc):
    """Per ogni elemento fisso: (zona interna, contorno) come maschere booleane."""
    nomi = {"sinistra": 2, "destra": 3, "dietro": 4, "fondo": 5}
    u, v = _uv_parete(rc["punto"], rc["superficie"], s["h"])
    imp = np.maximum(rc["impronta"] * 2.2, 0.012)
    risultati = []
    for f in s["fissi"]:
        su_parete = (rc["superficie"] == nomi[f["parete"]]) & (rc["mobile"] < 0)
        dentro = su_parete & (u >= f["u"][0]) & (u <= f["u"][1]) & (v >= f["v"][0]) & (v <= f["v"][1])
        bordo = dentro & ((u - f["u"][0] < imp) | (f["u"][1] - u < imp) | (v - f["v"][0] < imp) | (f["v"][1] - v < imp))
        risultati.append((dentro, bordo))
    return risultati


def _spigoli_mobile(m, rc, i):
    loc = rc["locale"]
    sel = rc["mobile"] == i
    imp = np.maximum(rc["impronta"] * 1.6, 0.008)
    if m.get("forma") == "cilindro":
        r = np.hypot(loc[..., 0], loc[..., 2])
        return sel & ((np.abs(loc[..., 1] - m["A"]) < imp) & (np.abs(r - m["L"] / 2) < imp * 2) |
                      (np.abs(loc[..., 1]) < imp))
    vicini = ((np.abs(np.abs(loc[..., 0]) - m["L"] / 2) < imp).astype(np.int8) +
              (np.abs(np.abs(loc[..., 2]) - m["P"] / 2) < imp).astype(np.int8) +
              ((np.abs(loc[..., 1]) < imp) | (np.abs(loc[..., 1] - max(m["A"], 0.01)) < imp)).astype(np.int8))
    return sel & (vicini >= 2)


def _spigoli_stanza(s, rc):
    p = rc["punto"]
    imp = np.maximum(rc["impronta"] * 1.4, 0.008)
    vicino = ((np.abs(p[..., 0] - s["XL"]) < imp).astype(np.int8) + (np.abs(p[..., 0] - s["XR"]) < imp) +
              (np.abs(p[..., 2] - s["ZB"]) < imp) + (np.abs(p[..., 2] - s["ZW"]) < imp) +
              (np.abs(p[..., 1] + s["h"]) < imp) + (np.abs(p[..., 1] - (s["H"] - s["h"])) < imp))
    return (vicino >= 2) & (rc["mobile"] < 0)


def _pixel(p3, w, h):
    x, y, z = p3
    lon = math.atan2(x, z)
    lat = math.atan2(y, math.hypot(x, z))
    return int((lon / (2 * math.pi) + 0.5) * w), int((0.5 - lat / math.pi) * h)


def _etichetta_mobile(m):
    nome = m.get("nome", "MOBILE").upper()
    if m.get("forma") == "cilindro":
        return f"{nome} Ø{round(m['L'] * 100)}"
    if m["A"] < 0.05:
        return f"{nome} {round(m['L'] * 100)}×{round(m['P'] * 100)}"
    return f"{nome} {round(m['L'] * 100)} cm"


def _scrivi(img_bgr, etichette, w):
    """Scrive le etichette (testo, posizione, colore) con un font vero (accenti e Ø)."""
    pil = Image.fromarray(img_bgr[..., ::-1])
    disegno = ImageDraw.Draw(pil)
    font = _font(max(18, w // 95))
    for testo, (x, y), colore in etichette:
        box = disegno.textbbox((0, 0), testo, font=font)
        tw, th = box[2] - box[0], box[3] - box[1]
        x = min(max(x, tw / 2 + 12), w - tw / 2 - 12)     # dentro l'immagine
        x0, y0 = int(x - tw / 2), int(y - th / 2)
        pad = max(4, w // 600)
        disegno.rounded_rectangle((x0 - pad * 2, y0 - pad, x0 + tw + pad * 2, y0 + th + pad * 2),
                                  radius=pad * 2, fill=(255, 255, 255), outline=colore[::-1], width=max(2, pad // 2))
        disegno.text((x0, y0 - box[1] // 2), testo, fill=colore[::-1], font=font)
    return np.array(pil)[..., ::-1].copy()


def guida_controllo(s, foto, larghezza=3840, griglia=0.5, rc=None):
    """Il 360 originale con griglia a pavimento, box dei mobili ed elementi fissi in rosso."""
    rc = rc or ray_casting(s, larghezza)
    h = larghezza // 2
    out = cv2.resize(foto, (larghezza, h), interpolation=cv2.INTER_AREA).astype(np.float32)
    libero = rc["mobile"] < 0

    # griglia azzurra a passo 50 cm sul pavimento
    pav = (rc["superficie"] == 0) & libero
    p = rc["punto"]
    imp = np.maximum(rc["impronta"] * 0.9, 0.006)
    fx = np.abs(((p[..., 0] / griglia) + 0.5) % 1 - 0.5) * griglia
    fz = np.abs(((p[..., 2] / griglia) + 0.5) % 1 - 0.5) * griglia
    linee = pav & ((fx < imp) | (fz < imp)) & (rc["t"] < 12)
    azzurro = np.array([255, 190, 60], np.float32)
    out[linee] = out[linee] * 0.25 + azzurro * 0.75

    # spigoli della stanza (sottili, scuri)
    out[_spigoli_stanza(s, rc)] = (40, 40, 40)

    # elementi fissi: velo rosso leggero + contorno rosso
    etichette = []
    rosso = np.array([40, 40, 220], np.float32)
    for f, (dentro, bordo) in zip(s["fissi"], _maschere_fissi(s, rc)):
        out[dentro] = out[dentro] * 0.82 + rosso * 0.18
        out[cv2.dilate(bordo.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0] = rosso
        cu, cv_ = sum(f["u"]) / 2, sum(f["v"]) / 2
        punto = _punto_parete(s, f["parete"], cu, cv_)
        etichette.append((f"NON SPOSTARE · {f['nome'].upper()}", _pixel(punto, larghezza, h), (40, 40, 220)))

    # mobili: box semitrasparenti colorati con spigoli
    for i, m in enumerate(s["mobili"]):
        colore = np.array(COLORI_MOBILI[i % len(COLORI_MOBILI)], np.float32)
        sel = rc["mobile"] == i
        out[sel] = out[sel] * 0.5 + colore * 0.5
        spig = cv2.dilate(_spigoli_mobile(m, rc, i).astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
        out[spig] = colore * 0.6
        cima = (m["centro_m"][0], -s["h"] + m["quota_m"] + max(m["A"], 0.01) + 0.12, m["centro_m"][1])
        etichette.append((_etichetta_mobile(m), _pixel(_dal_sistema_stanza(s, cima), larghezza, h),
                          tuple(int(c * 0.7) for c in colore)))
    # lettera di ogni parete (A = fondo, B = destra, C = dietro, D = sinistra), a 2 m da terra
    yl = 2.0 - s["h"]
    for lettera, p3 in (("A", ((s["XL"] + s["XR"]) / 2, yl, s["ZW"])), ("B", (s["XR"], yl, (s["ZB"] + s["ZW"]) / 2)),
                        ("C", ((s["XL"] + s["XR"]) / 2, yl, s["ZB"])), ("D", (s["XL"], yl, (s["ZB"] + s["ZW"]) / 2))):
        etichette.append((f"PARETE {lettera}", _pixel(_dal_sistema_stanza(s, p3), larghezza, h), (110, 110, 110)))
    out = np.clip(out, 0, 255).astype(np.uint8)
    return _scrivi(out, etichette, larghezza), rc


def guida_pulita(s, larghezza=3840, rc=None):
    """La stanza 'nuda': pareti grigie, pavimento chiaro, fissi e mobili colorati. Niente testo né griglia."""
    rc = rc or ray_casting(s, larghezza)
    toni = np.array([[205, 205, 205], [245, 245, 245], [175, 175, 175], [185, 185, 185],
                     [165, 165, 165], [195, 195, 195]], np.uint8)
    out = toni[rc["superficie"]]
    for f, (dentro, _) in zip(s["fissi"], _maschere_fissi(s, rc)):
        out[dentro] = TIPI_FISSI.get(f["tipo"], (180, 180, 180))
    for i, m in enumerate(s["mobili"]):
        out[rc["mobile"] == i] = COLORI_MOBILI[i % len(COLORI_MOBILI)]
    out[_spigoli_stanza(s, rc)] = (90, 90, 90)
    return out, rc


def _dal_sistema_stanza(s, p):
    """Da coordinate stanza a coordinate mondo (camera)."""
    c, sn = math.cos(s["theta"]), math.sin(s["theta"])
    x, y, z = p
    return (c * x - sn * z, y, sn * x + c * z)


def _punto_parete(s, parete, u, v):
    y = v - s["h"]
    p = {"sinistra": (s["XL"], y, u), "destra": (s["XR"], y, u), "dietro": (u, y, s["ZB"]),
         "fondo": (u, y, s["ZW"])}[parete]
    return _dal_sistema_stanza(s, p)


def pianta(s, lato=900):
    """Pianta vista dall'alto con misure, fotocamera, elementi fissi e mobili."""
    W, P = s["XR"] - s["XL"], s["ZW"] - s["ZB"]
    margine = 110
    scala = (lato - 2 * margine) / max(W, P)
    img = Image.new("RGB", (lato, lato), (250, 249, 246))
    d = ImageDraw.Draw(img)
    f_grande, f_piccolo = _font(22), _font(16)
    ox = (lato - W * scala) / 2
    oy = (lato - P * scala) / 2

    def xy(x, z):            # z = fondo in alto nella pianta
        return ox + (x - s["XL"]) * scala, oy + (s["ZW"] - z) * scala

    d.rectangle((*xy(s["XL"], s["ZW"]), *xy(s["XR"], s["ZB"])), outline=(30, 30, 30), width=6, fill=(255, 255, 255))
    # i tappeti (bassi) si disegnano per primi, così non coprono gli altri mobili
    for i, m in sorted(enumerate(s["mobili"]), key=lambda im: im[1]["A"]):
        b, g, r = COLORI_MOBILI[i % len(COLORI_MOBILI)]
        if m.get("forma") == "cilindro":
            cx, cz = xy(*m["centro_m"])
            rr = m["L"] / 2 * scala
            d.ellipse((cx - rr, cz - rr, cx + rr, cz + rr), fill=(r, g, b, 120), outline=(r // 2, g // 2, b // 2), width=2)
        else:
            d.polygon([xy(*p) for p in angoli_mobile(m)], fill=(r, g, b), outline=(r // 2, g // 2, b // 2))
        cx, cz = xy(*m["centro_m"])
        d.text((cx, cz), m.get("nome", ""), fill=(20, 20, 20), font=f_piccolo, anchor="mm")
    colori_fissi = {"porta": (110, 60, 40), "finestra": (60, 150, 230), "porta-finestra": (60, 150, 230),
                    "passaggio": (40, 40, 40)}
    for f in s["fissi"]:
        u0, u1 = f["u"]
        a, b = {"sinistra": ((s["XL"], u0), (s["XL"], u1)), "destra": ((s["XR"], u0), (s["XR"], u1)),
                "dietro": ((u0, s["ZB"]), (u1, s["ZB"])), "fondo": ((u0, s["ZW"]), (u1, s["ZW"]))}[f["parete"]]
        d.line((*xy(*a), *xy(*b)), fill=colori_fissi.get(f["tipo"], (220, 40, 40)), width=12)
    # fotocamera e zona da lasciare libera (1,3 m)
    cx, cz = xy(0, 0)
    r13 = 1.3 * scala
    for k in range(0, 360, 12):
        a0, a1 = math.radians(k), math.radians(k + 6)
        d.line((cx + r13 * math.cos(a0), cz + r13 * math.sin(a0), cx + r13 * math.cos(a1), cz + r13 * math.sin(a1)),
               fill=(200, 160, 120), width=2)
    d.ellipse((cx - 9, cz - 9, cx + 9, cz + 9), fill=(168, 121, 74))
    d.text((cx, cz + 22), "fotocamera", fill=(120, 90, 60), font=f_piccolo, anchor="mm")
    # niente quote: le misure assolute non sono ancora verificate, la pianta è solo uno schema
    return np.array(img)[..., ::-1].copy()
