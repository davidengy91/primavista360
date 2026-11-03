"""
Rilievo geometrico della stanza dal 360 ("radar geometrico").

La fotocamera è a un'altezza nota (1,50 m) e livellata. Quindi ogni punto del pavimento visto nel 360
ha una posizione 3D precisa: se lo guardo con un angolo di X gradi sotto l'orizzonte, dista
1,50 / tan(X) metri. Da qui:
- dagli angoli pavimento-muro indicati da Claude si ricava la pianta in metri;
- dagli angoli muro-soffitto l'altezza della stanza;
- dalla base dei mobili il loro ingombro a terra.

Poi si disegna tutto nella proiezione 360 esatta (spigoli, linee del pavimento dritte, box dei mobili):
è la guida che riceve il modello immagini.
"""
import math

import cv2
import numpy as np

from .geometria import matrice_rotazione

ALTEZZA_CAMERA = 1.50


# ------------------------------------------------------------------ geometria di base

def direzione_da_vista(v, x, y):
    """Direzione 3D (mondo) di un punto (x, y in 0-1000) di una vista."""
    f = 500 / math.tan(math.radians(v["fov"]) / 2)
    d = np.array([(x - 500) / f, -(y - 500) / f, 1.0])
    d = matrice_rotazione(v["yaw"], v["pitch"], v.get("roll", 0.0)) @ d
    return d / np.linalg.norm(d)


def punto_a_terra(d, h=ALTEZZA_CAMERA):
    """Dove la direzione d incontra il pavimento: (x, z) in metri, oppure None se guarda in alto."""
    if d[1] > -0.03:
        return None
    t = -h / d[1]
    p = t * d
    return np.array([p[0], p[2]]) if np.hypot(p[0], p[2]) < 15 else None


def _ruota(punti, angolo):
    c, s = math.cos(angolo), math.sin(angolo)
    return punti @ np.array([[c, s], [-s, c]])


# ------------------------------------------------------------------ pianta della stanza

def _pianta(angoli):
    """Dagli angoli a terra (anche imprecisi) ricava una pianta con pareti ad angolo retto."""
    # unisce i punti doppi (stesso angolo visto da due viste)
    uniti = []
    for p in angoli:
        for u in uniti:
            if np.linalg.norm(u["p"] / u["n"] - p) < 0.35:
                u["p"] += p
                u["n"] += 1
                break
        else:
            uniti.append({"p": p.copy(), "n": 1})
    punti = np.array([u["p"] / u["n"] for u in uniti])
    if len(punti) < 3:
        return None, 0.0
    punti = punti[np.argsort(np.arctan2(punti[:, 0], punti[:, 1]))]   # in ordine attorno alla fotocamera
    lati = np.roll(punti, -1, axis=0) - punti
    angoli_lati = np.arctan2(lati[:, 1], lati[:, 0])
    pesi = np.linalg.norm(lati, axis=1)
    # orientamento principale delle pareti (media circolare di 4*angolo)
    theta = math.atan2((pesi * np.sin(4 * angoli_lati)).sum(), (pesi * np.cos(4 * angoli_lati)).sum()) / 4
    r = _ruota(punti, -theta)
    n = len(r)
    orizzontale = [abs(r[(i + 1) % n, 0] - r[i, 0]) >= abs(r[(i + 1) % n, 1] - r[i, 1]) for i in range(n)]
    valore = [((r[i, 1] + r[(i + 1) % n, 1]) / 2) if orizzontale[i] else ((r[i, 0] + r[(i + 1) % n, 0]) / 2)
              for i in range(n)]
    nuovi = []
    for i in range(n):
        prec, succ = (i - 1) % n, i
        if orizzontale[prec] == orizzontale[succ]:
            continue                     # punto in mezzo a una parete dritta: non è un angolo
        if orizzontale[succ]:
            nuovi.append([valore[prec], valore[succ]])
        else:
            nuovi.append([valore[succ], valore[prec]])
    if len(nuovi) < 3:
        nuovi = r.tolist()
    return _ruota(np.array(nuovi), theta), theta


def costruisci_stanza(analisi, viste, h=ALTEZZA_CAMERA):
    """Restituisce un dizionario con pianta, altezza, mobili (in metri) oppure None se il rilievo non basta."""
    angoli = []
    for p in analisi.get("angoli_pavimento", []):
        v = viste.get(p["vista"])
        if v is None:
            continue
        a = punto_a_terra(direzione_da_vista(v, p["x"], p["y"]), h)
        if a is not None:
            angoli.append(a)
    pianta, theta = _pianta(angoli)
    if pianta is None:
        return None

    # altezza: angolo muro-soffitto sopra l'angolo della pianta più vicino in direzione
    altezze = []
    for p in analisi.get("angoli_soffitto", []):
        v = viste.get(p["vista"])
        if v is None:
            continue
        d = direzione_da_vista(v, p["x"], p["y"])
        if d[1] <= 0.03:
            continue
        az = math.atan2(d[0], d[2])
        vicino = min(pianta, key=lambda q: abs(((math.atan2(q[0], q[1]) - az) + math.pi) % (2 * math.pi) - math.pi))
        distanza = np.hypot(*vicino)
        altezze.append(h + distanza * d[1] / np.hypot(d[0], d[2]))
    altezza = float(np.clip(np.median(altezze), 2.2, 4.5)) if altezze else 2.70

    # mobili: spigolo anteriore a terra + profondità verso il muro
    mobili = []
    for e in analisi.get("elementi", []):
        if e.get("categoria") != "rinnova" or len(e.get("base", [])) != 4 or e.get("base_vista") not in viste:
            continue
        v = viste[e["base_vista"]]
        a = punto_a_terra(direzione_da_vista(v, e["base"][0], e["base"][1]), h)
        b = punto_a_terra(direzione_da_vista(v, e["base"][2], e["base"][3]), h)
        if a is None or b is None or np.linalg.norm(b - a) < 0.15:
            continue
        lato = (b - a) / np.linalg.norm(b - a)
        normale = np.array([-lato[1], lato[0]])
        if np.dot(normale, (a + b) / 2) < 0:      # la profondità va lontano dalla fotocamera
            normale = -normale
        prof = max(0.02, e.get("profondita_cm", 0) / 100)
        base = np.array([a, b, b + normale * prof, a + normale * prof])
        mobili.append({"id": e["id"], "nome": e["nome"], "base": base, "altezza": max(0.0, e.get("altezza_cm", 0) / 100)})

    r = _ruota(pianta, -theta)
    larghezza, profondita = float(np.ptp(r[:, 0])), float(np.ptp(r[:, 1]))
    area = 0.5 * abs(np.dot(pianta[:, 0], np.roll(pianta[:, 1], 1)) - np.dot(pianta[:, 1], np.roll(pianta[:, 0], 1)))
    return {"pianta": pianta, "theta": theta, "altezza": altezza, "h_camera": h, "mobili": mobili,
            "pavimento": analisi.get("pavimento_nuovo", "lastre"), "formato_cm": analisi.get("formato_cm") or [120, 60],
            "misure": {"larghezza_m": round(larghezza, 2), "profondita_m": round(profondita, 2),
                       "altezza_m": round(altezza, 2), "superficie_mq": round(float(area), 1)}}


# ------------------------------------------------------------------ disegno nel 360

def _pixel(p3, w, h):
    x, y, z = p3
    lon = math.atan2(x, z)
    lat = math.atan2(y, math.hypot(x, z))
    return (lon / (2 * math.pi) + 0.5) * w, (0.5 - lat / math.pi) * h


def _segmento(img, a, b, colore, spessore):
    """Disegna un segmento 3D nel 360 (diventa una curva, come nella realtà)."""
    w, h = img.shape[1], img.shape[0]
    n = int(max(24, np.linalg.norm(np.array(b) - np.array(a)) * 120))
    pts = [_pixel(np.array(a) + (np.array(b) - np.array(a)) * t, w, h) for t in np.linspace(0, 1, n)]
    tratto = [pts[0]]
    for p in pts[1:]:
        if abs(p[0] - tratto[-1][0]) > w / 2:            # attraversa la giuntura del 360
            cv2.polylines(img, [np.int32(tratto)], False, colore, spessore, cv2.LINE_AA)
            tratto = []
        tratto.append(p)
    if len(tratto) > 1:
        cv2.polylines(img, [np.int32(tratto)], False, colore, spessore, cv2.LINE_AA)


def _a3d(p2, y):
    return (float(p2[0]), y, float(p2[1]))


def _linee_pavimento(stanza):
    """Le linee di posa del pavimento (dritte, parallele alla parete principale), tagliate sulla pianta."""
    theta, pianta = stanza["theta"], stanza["pianta"]
    r = _ruota(pianta, -theta)
    contorno = np.float32(r * 100)                       # in cm per pointPolygonTest
    lung, larg = (stanza["formato_cm"] + [60, 60])[:2]
    lung, larg = max(lung, 10) / 100, max(larg, 5) / 100
    x0, x1, z0, z1 = r[:, 0].min(), r[:, 0].max(), r[:, 1].min(), r[:, 1].max()
    lungo_x = (x1 - x0) >= (z1 - z0)                     # le doghe seguono il lato lungo
    passi = [(larg, not lungo_x)]                        # linee parallele al lato lungo
    if stanza["pavimento"] != "doghe":
        passi.append((lung, lungo_x))                    # griglia per lastre e piastrelle
    linee = []
    for passo, lungo_z in passi:
        if lungo_z:     # linee a x costante
            for x in np.arange(math.ceil(x0 / passo) * passo, x1, passo):
                linee += _taglia(contorno, [(x, z) for z in np.linspace(z0, z1, 200)])
        else:
            for z in np.arange(math.ceil(z0 / passo) * passo, z1, passo):
                linee += _taglia(contorno, [(x, z) for x in np.linspace(x0, x1, 200)])
    return [(_ruota(np.array([a]), theta)[0], _ruota(np.array([b]), theta)[0]) for a, b in linee]


def _taglia(contorno, punti):
    """Tiene solo i pezzi della linea che stanno dentro la pianta."""
    pezzi, inizio, prec = [], None, None
    for p in punti:
        dentro = cv2.pointPolygonTest(contorno, (p[0] * 100, p[1] * 100), False) >= 0
        if dentro and inizio is None:
            inizio = p
        if not dentro and inizio is not None:
            pezzi.append((inizio, prec))
            inizio = None
        prec = p
    if inizio is not None:
        pezzi.append((inizio, prec))
    return [(np.array(a), np.array(b)) for a, b in pezzi if np.hypot(b[0] - a[0], b[1] - a[1]) > 0.05]


def disegna_radar(stanza, larghezza=3840, sfondo=None):
    """Immagine guida nel 360: spigoli della stanza, linee del pavimento, box dei mobili.
    sfondo: immagine (stessa proiezione) su cui disegnare, altrimenti bianco."""
    h = larghezza // 2
    img = np.full((h, larghezza, 3), 255, np.uint8) if sfondo is None else \
        cv2.resize(sfondo, (larghezza, h), interpolation=cv2.INTER_AREA).copy()
    sp = max(2, larghezza // 1200)
    yp, ys = -stanza["h_camera"], stanza["altezza"] - stanza["h_camera"]
    for a, b in _linee_pavimento(stanza):
        _segmento(img, _a3d(a, yp), _a3d(b, yp), (175, 175, 175), max(1, sp - 1))
    pianta = stanza["pianta"]
    for i in range(len(pianta)):
        a, b = pianta[i], pianta[(i + 1) % len(pianta)]
        _segmento(img, _a3d(a, yp), _a3d(b, yp), (20, 20, 20), sp + 1)   # muro-pavimento
        _segmento(img, _a3d(a, ys), _a3d(b, ys), (20, 20, 20), sp + 1)   # muro-soffitto
        _segmento(img, _a3d(a, yp), _a3d(a, ys), (20, 20, 20), sp + 1)   # spigolo verticale
    for m in stanza["mobili"]:
        colore = (40, 120, 230) if m["altezza"] < 0.05 else (200, 90, 20)   # tappeti arancio, mobili blu
        base = m["base"]
        for i in range(4):
            a, b = base[i], base[(i + 1) % 4]
            _segmento(img, _a3d(a, yp), _a3d(b, yp), colore, sp + 1)
            if m["altezza"] >= 0.05:
                top = yp + m["altezza"]
                _segmento(img, _a3d(a, top), _a3d(b, top), colore, sp + 1)
                _segmento(img, _a3d(a, yp), _a3d(a, top), colore, sp + 1)
    return img


def stanza_serializzabile(stanza):
    """Versione JSON del rilievo (per salvarlo e mostrarlo)."""
    if stanza is None:
        return None
    return {"misure": stanza["misure"], "pianta": np.round(stanza["pianta"], 3).tolist(),
            "altezza": stanza["altezza"], "h_camera": stanza["h_camera"], "theta": stanza["theta"],
            "pavimento": stanza["pavimento"], "formato_cm": stanza["formato_cm"],
            "mobili": [{"id": m["id"], "nome": m["nome"], "base": np.round(m["base"], 3).tolist(),
                        "altezza": m["altezza"]} for m in stanza["mobili"]]}
