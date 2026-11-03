"""
Ricostruzione della stanza come "scatola" a partire dai clic del fotografo nel viewer 360.

Idea: la fotocamera è a un'altezza nota (default 1,50 m) e in bolla. Un punto del pavimento visto
con un angolo di X gradi sotto l'orizzonte dista altezza / tan(X) metri. Quindi dai 4 angoli
pavimento-parete cliccati si ricavano le pareti (XL, XR, ZB, ZW) e le misure vere in metri;
da un clic su un angolo del soffitto l'altezza.

Sistema di riferimento della stanza (dopo aver ruotato di theta per allineare le pareti):
  x = destra/sinistra, z = avanti/dietro, y = alto (pavimento a y = -altezza_camera).
Le direzioni dei clic arrivano come (yaw, pitch) in gradi, come le dà il viewer Pannellum.
"""
import math

import numpy as np

PARETI = ("sinistra", "destra", "dietro", "fondo")     # x = XL, x = XR, z = ZB, z = ZW

PRESET_MOBILI = {
    "Divano": {"larghezza": 240, "profondita": 95, "altezza": 85, "forma": "box", "muro": True},
    "Divano angolare": {"larghezza": 280, "profondita": 180, "altezza": 85, "forma": "box", "muro": True},
    "Poltrona": {"larghezza": 80, "profondita": 85, "altezza": 80, "forma": "box", "muro": False},
    "Tavolino": {"larghezza": 90, "profondita": 90, "altezza": 40, "forma": "cilindro", "muro": False},
    "Tappeto": {"larghezza": 200, "profondita": 300, "altezza": 1, "forma": "box", "muro": False},
    "Mobile TV": {"larghezza": 180, "profondita": 40, "altezza": 50, "forma": "box", "muro": True},
    "Libreria": {"larghezza": 120, "profondita": 35, "altezza": 200, "forma": "box", "muro": True},
    "Tavolo rettangolare": {"larghezza": 160, "profondita": 90, "altezza": 75, "forma": "box", "muro": False},
    "Tavolo tondo": {"larghezza": 110, "profondita": 110, "altezza": 75, "forma": "cilindro", "muro": False},
    "Sedia": {"larghezza": 45, "profondita": 50, "altezza": 85, "forma": "box", "muro": False},
    "Basi cucina": {"larghezza": 300, "profondita": 60, "altezza": 90, "forma": "box", "muro": True},
    "Pensili cucina": {"larghezza": 300, "profondita": 35, "altezza": 70, "forma": "box", "muro": True, "quota": 145},
    "Colonna frigo": {"larghezza": 60, "profondita": 60, "altezza": 215, "forma": "box", "muro": True},
    "Isola cucina": {"larghezza": 200, "profondita": 90, "altezza": 90, "forma": "box", "muro": False},
    "Letto matrimoniale": {"larghezza": 160, "profondita": 200, "altezza": 100, "forma": "box", "muro": True},
    "Letto singolo": {"larghezza": 90, "profondita": 200, "altezza": 90, "forma": "box", "muro": True},
    "Comodino": {"larghezza": 50, "profondita": 40, "altezza": 50, "forma": "box", "muro": True},
    "Armadio": {"larghezza": 240, "profondita": 60, "altezza": 240, "forma": "box", "muro": True},
    "Comò": {"larghezza": 120, "profondita": 50, "altezza": 85, "forma": "box", "muro": True},
    "Scrivania": {"larghezza": 120, "profondita": 60, "altezza": 75, "forma": "box", "muro": True},
    "Mobile bagno": {"larghezza": 100, "profondita": 50, "altezza": 55, "forma": "box", "muro": True, "quota": 30},
    "Doccia": {"larghezza": 120, "profondita": 90, "altezza": 200, "forma": "box", "muro": True},
    "Vasca": {"larghezza": 170, "profondita": 75, "altezza": 55, "forma": "box", "muro": True},
    "WC sospeso": {"larghezza": 37, "profondita": 55, "altezza": 40, "forma": "box", "muro": True, "quota": 0},
    "Bidet sospeso": {"larghezza": 37, "profondita": 55, "altezza": 40, "forma": "box", "muro": True, "quota": 0},
    "Termoarredo": {"larghezza": 50, "profondita": 8, "altezza": 120, "forma": "box", "muro": True},
    # elementi A PARETE: "quota" = altezza da terra del bordo basso (cm)
    "Specchio": {"larghezza": 80, "profondita": 2, "altezza": 70, "forma": "box", "muro": True, "quota": 105},
    "Specchio retroilluminato": {"larghezza": 80, "profondita": 3, "altezza": 70, "forma": "box", "muro": True,
                                 "quota": 105, "led": True},
    "Pensile bagno": {"larghezza": 60, "profondita": 22, "altezza": 60, "forma": "box", "muro": True, "quota": 125},
    "Mensola": {"larghezza": 60, "profondita": 20, "altezza": 3, "forma": "box", "muro": True, "quota": 110},
    "Colonna bagno": {"larghezza": 35, "profondita": 32, "altezza": 160, "forma": "box", "muro": True, "quota": 20},
    "Applique": {"larghezza": 10, "profondita": 10, "altezza": 22, "forma": "box", "muro": True, "quota": 165},
}

TIPI_FISSI = {"porta": (40, 60, 110), "finestra": (235, 200, 120), "porta-finestra": (235, 200, 120),
              "termosifone": (245, 245, 245), "condizionatore": (230, 230, 230), "presa": (200, 200, 200),
              "passaggio": (60, 60, 60), "altro": (180, 180, 180)}          # colori BGR per la guida "pulita"


# ------------------------------------------------------------------ direzioni e piani

def direzione(yaw, pitch):
    """Direzione 3D (x destra, y alto, z avanti) da yaw/pitch in gradi (convenzione Pannellum)."""
    y, p = math.radians(yaw), math.radians(pitch)
    return np.array([math.cos(p) * math.sin(y), math.sin(p), math.cos(p) * math.cos(y)])


def ruota_xz(v, theta):
    """Ruota un vettore (x, y, z) o (x, z) attorno all'asse verticale di -theta (mondo -> stanza)."""
    c, s = math.cos(theta), math.sin(theta)
    if len(v) == 3:
        return np.array([c * v[0] + s * v[2], v[1], -s * v[0] + c * v[2]])
    return np.array([c * v[0] + s * v[1], -s * v[0] + c * v[1]])


def a_terra(d, h):
    """Punto del pavimento (x, z) visto nella direzione d, oppure None se d non guarda in basso."""
    if d[1] > -0.02:
        return None
    t = -h / d[1]
    return np.array([t * d[0], t * d[2]])


# ------------------------------------------------------------------ costruzione della stanza

def _risolvi(dati, h):
    """Trova la scatola (rotazione theta + pareti XL, XR, ZB, ZW) che rispetta meglio TUTTI i clic:
    - angoli del pavimento (punto a terra completo);
    - spigoli verticali tra due pareti (conta solo la direzione orizzontale: si possono cliccare anche in alto);
    - punti del battiscopa di ogni parete (gruppi A, B, C, D).
    Per ogni rotazione possibile il problema è lineare: si risolve e si tiene la rotazione con l'errore minore."""
    angoli = [a for a in (a_terra(direzione(*c), h) for c in dati.get("angoli", [])) if a is not None]
    spigoli = [math.radians(c[0]) for c in dati.get("spigoli", [])]
    gruppi = []
    for punti in (dati.get("pareti") or {}).values():
        pts = [a for a in (a_terra(direzione(*c), h) for c in punti) if a is not None]
        if len(pts) >= 2:
            gruppi.append(np.array(pts))
    if not angoli and not gruppi:
        return None, "Clicca almeno gli angoli del pavimento oppure il battiscopa di alcune pareti."

    migliore = None
    for theta in np.radians(np.arange(-45, 45, 0.25)):
        righe, valori = [], []
        indice = {"XL": 0, "XR": 1, "ZB": 2, "ZW": 3}

        def riga(var, valore, peso=1.0):
            r = np.zeros(4)
            r[indice[var]] = peso
            righe.append(r)
            valori.append(valore * peso)

        for a in angoli:
            x, z = ruota_xz(a, theta)
            riga("XL" if x < 0 else "XR", x)
            riga("ZB" if z < 0 else "ZW", z)
        for g in gruppi:
            q = np.array([ruota_xz(a, theta) for a in g])
            if np.ptp(q[:, 0]) < np.ptp(q[:, 1]):        # parete a x costante
                var = "XL" if q[:, 0].mean() < 0 else "XR"
                for x in q[:, 0]:
                    riga(var, x)
            else:
                var = "ZB" if q[:, 1].mean() < 0 else "ZW"
                for z in q[:, 1]:
                    riga(var, z)
        for yaw in spigoli:
            yr = yaw + theta
            sx, cz = math.sin(yr), math.cos(yr)
            r = np.zeros(4)
            r[indice["XL" if sx < 0 else "XR"]] = cz        # X*cos - Z*sin = 0 (lo spigolo sta su quel raggio)
            r[indice["ZB" if cz < 0 else "ZW"]] = -sx
            righe.append(r)
            valori.append(0.0)
        A, b = np.array(righe), np.array(valori)
        if np.linalg.matrix_rank(A) < 4:
            continue
        w, *_ = np.linalg.lstsq(A, b, rcond=None)
        if not (w[0] < -0.2 and w[1] > 0.2 and w[2] < -0.2 and w[3] > 0.2):
            continue
        errore = float(np.sqrt(np.mean((A @ w - b) ** 2)))
        if migliore is None or errore < migliore[0]:
            migliore = (errore, float(theta), w)
    if migliore is None:
        return None, ("I clic non bastano a chiudere la stanza: servono informazioni su tutte e 4 le pareti "
                      "(angoli, spigoli o battiscopa).")
    return migliore, None


def costruisci(dati):
    """dati: dizionario salvato dall'interfaccia (room.json). Restituisce la stanza calcolata o un errore.
    Se 'tara_porta' è attivo e c'è una porta segnata, l'altezza della camera si ricava dall'altezza
    della porta (tutte le misure sono proporzionali all'altezza della camera)."""
    if dati.get("pianta"):
        # stanza da piantina: le misure sono già quelle vere, niente tarature
        from .p3_pianta import in_dati
        return _costruisci({**dati, **in_dati(dati["pianta"])})
    porte = [f for f in dati.get("fissi", []) if f.get("tipo") == "porta"]
    if dati.get("tara_porta") and porte:
        prova = _costruisci({**dati, "altezza_camera": 1.0})
        fisse = [f for f in prova.get("fissi", []) if f["tipo"] == "porta"]
        if "errore" not in prova and fisse:
            alta = fisse[0]["v"][1] - fisse[0]["v"][0]          # altezza porta con camera a 1 m
            if alta > 0.3:
                h = float(dati.get("altezza_porta", 2.10)) / alta
                s = _costruisci({**dati, "altezza_camera": round(h, 3)})
                if "errore" not in s:
                    s["misure"]["altezza_camera_m"] = round(h, 2)
                    s["misure"]["tarata_con_porta"] = True
                return s
    # Senza porta: taratura col soffitto. Il rapporto soffitto/pavimento lo vede bene anche il rilievo automatico,
    # e nelle abitazioni il soffitto è quasi sempre 2,70 m (minimo di legge per camere e soggiorni).
    if dati.get("tara_soffitto", True) and dati.get("soffitto") and not dati.get("scatola") and not dati.get("altezza_soffitto"):
        # prova con la camera a 1,5 m (il soffitto calcolato è limitato tra 2 e 5 m: deve stare dentro i limiti)
        prova = _costruisci({**dati, "altezza_camera": 1.5})
        if "errore" not in prova and 2.01 < prova["H"] < 4.99:
            h = 1.5 * ALTEZZA_SOFFITTO_TIPICA / prova["H"]
            if 0.8 <= h <= 2.0:                                           # fotocamera su treppiede: valori sensati
                s = _costruisci({**dati, "altezza_camera": round(h, 3)})
                if "errore" not in s:
                    s["misure"]["altezza_camera_m"] = round(h, 2)
                    s["misure"]["tarata_con_soffitto"] = True
                return s
    return _costruisci(dati)


ALTEZZA_SOFFITTO_TIPICA = 2.70


# Oltre questo scarto (media tra angoli cliccati/trovati e scatola ricostruita) la stanza NON è affidabile:
# nelle stanze buone lo scarto è sotto 1 cm, quando HorizonNet sbaglia (stanza piena di mobili) supera il metro.
SOGLIA_SCARTO_CM = 20


def affidabile(stanza_serializzata):
    """True se la stanza ricostruita è attendibile (si può usare per la guida a ChatGPT)."""
    misure = (stanza_serializzata or {}).get("misure") or {}
    return float(misure.get("scarto_angoli_cm", 999)) <= SOGLIA_SCARTO_CM


def _costruisci(dati):
    h = float(dati.get("altezza_camera", 1.5))
    scatola = dati.get("scatola")
    if scatola:
        # pareti sistemate a mano trascinando le linee: valori in metri con camera a 1 m, scalati sull'altezza
        k = h / float(scatola.get("h", 1.0))
        theta = float(scatola["theta"])
        XL, XR, ZB, ZW = (float(scatola[c]) * k for c in ("XL", "XR", "ZB", "ZW"))
        if not (XL < 0 < XR and ZB < 0 < ZW):
            return {"errore": "Le pareti spostate lasciano la fotocamera fuori dalla stanza."}
        scarto = 0.0
        dati = {**dati, "altezza_soffitto": float(scatola["H"]) * k if scatola.get("H") else dati.get("altezza_soffitto")}
    else:
        soluzione, errore = _risolvi(dati, h)
        if errore:
            return {"errore": errore}
        scarto, theta, (XL, XR, ZB, ZW) = soluzione
    XL, XR, ZB, ZW = float(XL), float(XR), float(ZB), float(ZW)
    scarti = [scarto]

    stanza = {"h": h, "theta": theta, "XL": XL, "XR": XR, "ZB": ZB, "ZW": ZW, "H": 2.70}
    if dati.get("soffitto"):
        d = ruota_xz(direzione(*dati["soffitto"]), theta)
        dist = _distanza_parete_orizzontale(stanza, d)
        if d[1] > 0.02 and dist:
            stanza["H"] = float(np.clip(h + dist * d[1] / math.hypot(d[0], d[2]), 2.0, 5.0))
    if dati.get("altezza_soffitto"):
        stanza["H"] = float(dati["altezza_soffitto"])

    stanza["fissi"] = [f for f in (_fisso(stanza, f) for f in dati.get("fissi", [])) if f]
    stanza["mobili"] = [_mobile(stanza, m) for m in dati.get("mobili", [])]
    # luci scelte dall'impresa (faretti, plafoniere, sospensioni) e atmosfera del render
    stanza["luci"] = [l for l in dati.get("luci", []) if isinstance(l, dict) and l.get("centro")]
    stanza["atmosfera"] = dati.get("atmosfera", "giorno")
    stanza["misure"] = {"larghezza_m": round(XR - XL, 2), "profondita_m": round(ZW - ZB, 2),
                        "altezza_m": round(stanza["H"], 2), "superficie_mq": round((XR - XL) * (ZW - ZB), 1),
                        "scarto_angoli_cm": round(100 * float(np.mean(scarti)), 1),
                        "altezza_camera_m": round(h, 2)}
    stanza["avvisi"] = _avvisi(stanza)
    return stanza


def _distanza_parete_orizzontale(s, d):
    """Distanza orizzontale dalla camera alla parete nella direzione d (coordinate stanza)."""
    tt = []
    if d[0] < 0:
        tt.append(s["XL"] / d[0])
    if d[0] > 0:
        tt.append(s["XR"] / d[0])
    if d[2] < 0:
        tt.append(s["ZB"] / d[2])
    if d[2] > 0:
        tt.append(s["ZW"] / d[2])
    if not tt:
        return None
    t = min(tt)
    return t * math.hypot(d[0], d[2])


def colpisci_parete(s, d):
    """Su quale parete cade la direzione d (coord. stanza) e in che punto: (parete, u, v).
    u = posizione orizzontale lungo la parete (m), v = altezza dal pavimento (m)."""
    candidati = []
    if d[0] < 0:
        candidati.append(("sinistra", s["XL"] / d[0]))
    if d[0] > 0:
        candidati.append(("destra", s["XR"] / d[0]))
    if d[2] < 0:
        candidati.append(("dietro", s["ZB"] / d[2]))
    if d[2] > 0:
        candidati.append(("fondo", s["ZW"] / d[2]))
    parete, t = min(candidati, key=lambda c: c[1])
    return parete, *_uv(parete, t * d, s)


def _uv(parete, punto, s):
    u = punto[2] if parete in ("sinistra", "destra") else punto[0]
    return u, punto[1] + s["h"]


def sulla_parete(s, parete, d):
    """Punto (u, v) dove la direzione d incontra il piano di una parete data (anche se un'altra è più vicina)."""
    piano = {"sinistra": (0, s["XL"]), "destra": (0, s["XR"]), "dietro": (2, s["ZB"]), "fondo": (2, s["ZW"])}[parete]
    if abs(d[piano[0]]) < 1e-6:
        return None
    t = piano[1] / d[piano[0]]
    return _uv(parete, t * d, s) if t > 0 else None


def _fisso(s, f):
    """Elemento fisso: rettangolo su una parete, dai due clic sugli angoli opposti
    (oppure già in misure, quando la stanza viene da una piantina)."""
    if "parete" in f and "u" in f and "v" in f and "p1" not in f:
        return {"tipo": f.get("tipo", "altro"), "nome": f.get("nome") or f.get("tipo", "elemento"),
                "parete": f["parete"], "u": sorted(f["u"]), "v": [max(0.0, f["v"][0]), min(s["H"], f["v"][1])]}
    d1, d2 = ruota_xz(direzione(*f["p1"]), s["theta"]), ruota_xz(direzione(*f["p2"]), s["theta"])
    parete, u1, v1 = colpisci_parete(s, d1)
    uv2 = sulla_parete(s, parete, d2)
    if uv2 is None:
        return None
    u2, v2 = uv2
    return {"tipo": f.get("tipo", "altro"), "nome": f.get("nome") or f.get("tipo", "elemento"), "parete": parete,
            "u": sorted([u1, u2]), "v": [max(0.0, min(v1, v2)), min(s["H"], max(v1, v2))],
            "p1": f["p1"], "p2": f["p2"]}


def _mobile(s, m):
    """Mobile: box (o cilindro) a misura reale, centrato dove è stato cliccato sul pavimento.
    Se 'muro' è attivo si appoggia con il retro alla parete più vicina."""
    L, P, A = m["larghezza"] / 100, m["profondita"] / 100, m["altezza"] / 100
    quota = m.get("quota", 0) / 100
    if "centro" in m:                           # già in coordinate stanza (metri)
        cx, cz = m["centro"]
    else:
        p = a_terra(ruota_xz(direzione(*m["clic"]), s["theta"]), s["h"])
        cx, cz = (p if p is not None else (0.0, 2.0))
    rot = float(m.get("rotazione", 0))
    if m.get("muro") and m.get("forma", "box") == "box":
        # parete più vicina: il lato "profondità" diventa perpendicolare alla parete
        distanze = {"sinistra": cx - s["XL"], "destra": s["XR"] - cx, "dietro": cz - s["ZB"], "fondo": s["ZW"] - cz}
        parete = m["parete"] if m.get("parete") in distanze else min(distanze, key=distanze.get)
        rot = {"fondo": 0, "dietro": 180, "sinistra": 270, "destra": 90}[parete]
        g = 0.01
        if parete == "fondo":
            cz = s["ZW"] - P / 2 - g
        elif parete == "dietro":
            cz = s["ZB"] + P / 2 + g
        elif parete == "sinistra":
            cx = s["XL"] + P / 2 + g
        else:
            cx = s["XR"] - P / 2 - g
    return {**m, "centro_m": [round(float(cx), 3), round(float(cz), 3)], "rot": rot,
            "L": L, "P": P, "A": A, "quota_m": quota}


def angoli_mobile(m):
    """I 4 angoli a terra (coord. stanza) di un mobile box."""
    a = math.radians(m["rot"])
    c, s_ = math.cos(a), math.sin(a)
    ex, ez = np.array([c, -s_]), np.array([s_, c])       # asse larghezza e asse profondità
    centro = np.array(m["centro_m"])
    return [centro + ex * sx * m["L"] / 2 + ez * sz * m["P"] / 2 for sx, sz in ((-1, -1), (1, -1), (1, 1), (-1, 1))]


def _avvisi(s):
    avvisi = []
    for m in s["mobili"]:
        nome = m.get("nome", "mobile")
        if m.get("forma") == "cilindro":
            dist = math.hypot(*m["centro_m"]) - m["L"] / 2
            pts = [np.array(m["centro_m"])]
        else:
            pts = angoli_mobile(m)
            dist = min(_distanza_segmento(np.zeros(2), pts[i], pts[(i + 1) % 4]) for i in range(4))
            if _dentro(np.zeros(2), pts):
                dist = 0
        if dist < 1.3 and m.get("altezza", 0) > 2:
            avvisi.append(f"{nome}: è a {dist:.1f} m dalla fotocamera (sotto 1,3 m sembrerà enorme).")
        for p in pts:
            if not (s["XL"] - 0.05 <= p[0] <= s["XR"] + 0.05 and s["ZB"] - 0.05 <= p[1] <= s["ZW"] + 0.05):
                avvisi.append(f"{nome}: esce dalla stanza.")
                break
        for f in s["fissi"]:
            if f["tipo"] in ("porta", "porta-finestra", "passaggio") and _davanti_porta(s, f, pts):
                avvisi.append(f"{nome}: blocca {f['nome']}.")
    return avvisi


def _distanza_segmento(p, a, b):
    ab = b - a
    t = np.clip(np.dot(p - a, ab) / max(np.dot(ab, ab), 1e-9), 0, 1)
    return float(np.linalg.norm(p - (a + t * ab)))


def _dentro(p, poligono):
    def cross(a, b):
        return a[0] * b[1] - a[1] * b[0]
    segni = [cross(poligono[(i + 1) % 4] - poligono[i], p - poligono[i]) for i in range(4)]
    return all(x >= 0 for x in segni) or all(x <= 0 for x in segni)


def _davanti_porta(s, f, pts):
    """True se il mobile occupa i 70 cm davanti a una porta."""
    u0, u1 = f["u"]
    prof = 0.7
    if f["parete"] == "sinistra":
        zona = (s["XL"], s["XL"] + prof, u0, u1)
    elif f["parete"] == "destra":
        zona = (s["XR"] - prof, s["XR"], u0, u1)
    elif f["parete"] == "dietro":
        zona = (u0, u1, s["ZB"], s["ZB"] + prof)
    else:
        zona = (u0, u1, s["ZW"] - prof, s["ZW"])
    xs, zs = [p[0] for p in pts], [p[1] for p in pts]
    return not (max(xs) < zona[0] or min(xs) > zona[1] or max(zs) < zona[2] or min(zs) > zona[3])


def serializza(s):
    """Versione salvabile in room.json (solo numeri e testi)."""
    if "errore" in s:
        return s
    out = {k: s[k] for k in ("h", "theta", "XL", "XR", "ZB", "ZW", "H", "misure", "avvisi")}
    out["fissi"] = s["fissi"]
    out["mobili"] = [{k: v for k, v in m.items()} for m in s["mobili"]]
    out["luci"] = s.get("luci", [])
    out["atmosfera"] = s.get("atmosfera", "giorno")
    return out
