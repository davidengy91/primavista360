"""
Mappa della stanza ("radar"): trasforma i riquadri che Claude ha indicato nelle viste
in maschere precise sul 360, grazie alla geometria esatta delle viste.

Serve a:
- mostrare al fotografo cosa resta fisso, cosa si rinnova e cosa si toglie (con conferma);
- rimettere i pixel originali sugli elementi fissi dopo la generazione (identici per costruzione).
"""
import cv2
import numpy as np

from .geometria import proietta_vista_su_equi

COLORI = {"fisso": (64, 160, 47), "rinnova": (74, 121, 168), "togli": (58, 68, 192)}   # BGR
LARGHEZZA_MASCHERE = 2048


def _scegli_presenze(elemento, parametri_viste):
    """Un oggetto visto in più viste: si usa la vista dove è intero e più centrale (più precisa).
    Se in nessuna vista è intero, si uniscono tutte. Oggetti diversi nella stessa vista restano tutti."""
    valide = [p for p in elemento["presenze"] if p.get("vista") in parametri_viste and len(p.get("riquadro", [])) == 4]
    orizz = [p for p in valide if abs(parametri_viste[p["vista"]]["pitch"]) < 45]
    valide = orizz or valide           # zenit/nadir solo se l'oggetto non si vede altrove
    per_vista = {}
    for p in valide:
        per_vista.setdefault(p["vista"], []).append(p)

    def punteggio(vista):
        riquadri = per_vista[vista]
        interi = all(min(r["riquadro"][0], r["riquadro"][1]) > 15 and max(r["riquadro"][2], r["riquadro"][3]) < 985
                     for r in riquadri)
        cx = np.mean([(r["riquadro"][0] + r["riquadro"][2]) / 2 for r in riquadri])
        cy = np.mean([(r["riquadro"][1] + r["riquadro"][3]) / 2 for r in riquadri])
        return interi, -np.hypot(cx - 500, cy - 500)

    if not per_vista:
        return []
    migliore = max(per_vista, key=punteggio)
    return per_vista[migliore] if punteggio(migliore)[0] else valide


def maschera_elemento(elemento, parametri_viste, larghezza=LARGHEZZA_MASCHERE):
    """Maschera (0/1) dell'elemento sul 360, dai riquadri indicati da Claude nelle viste."""
    h = larghezza // 2
    totale = np.zeros((h, larghezza), np.float32)
    for p in _scegli_presenze(elemento, parametri_viste):
        v = parametri_viste.get(p["vista"])
        if v is None or len(p["riquadro"]) != 4:
            continue
        lato = 512
        x1, y1, x2, y2 = [int(np.clip(c, 0, 1000) / 1000 * lato) for c in p["riquadro"]]
        # riquadri vuoti o enormi (più di metà vista) sono imprecisi: si scartano
        if x2 <= x1 or y2 <= y1 or (x2 - x1) * (y2 - y1) > 0.5 * lato * lato:
            continue
        rett = np.zeros((lato, lato), np.float32)
        rett[y1:y2, x1:x2] = 1
        layer, copertura = proietta_vista_su_equi(rett, v["yaw"], v["pitch"], v["fov"], larghezza, h,
                                                  v.get("roll", 0.0), potenza_peso=0)
        totale = np.maximum(totale, np.where(copertura > 0, layer, 0))
    return (totale > 0.5).astype(np.uint8)


def calcola_maschere(analisi_dict, parametri_viste):
    """Dict id -> maschera per tutti gli elementi."""
    return {e["id"]: maschera_elemento(e, parametri_viste) for e in analisi_dict.get("elementi", [])}


def immagine_mappa(equi, elementi, maschere, larghezza=4096):
    """Il 360 originale con gli elementi colorati e numerati, per la schermata di conferma."""
    h = larghezza // 2
    base = cv2.resize(equi, (larghezza, h), interpolation=cv2.INTER_AREA)
    out = (base * 0.78).astype(np.uint8)
    # si disegnano prima i "togli", poi i "rinnova", per ultimi i "fissi" (i più importanti restano visibili)
    ordine = {"togli": 0, "rinnova": 1, "fisso": 2}
    numerati = sorted(enumerate(elementi, 1), key=lambda ne: ordine.get(ne[1]["categoria"], 0))
    for n, e in numerati:
        m = maschere.get(e["id"])
        if m is None or not m.any():
            continue
        m = cv2.resize(m, (larghezza, h), interpolation=cv2.INTER_NEAREST)
        colore = np.array(COLORI.get(e["categoria"], (200, 200, 200)), np.float32)
        zona = m > 0
        out[zona] = (base[zona] * 0.55 + colore * 0.45).astype(np.uint8)
        contorni, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(out, contorni, -1, tuple(int(c) for c in colore), 4)
        # numero al centro della parte più grande
        grande = max(contorni, key=cv2.contourArea)
        mom = cv2.moments(grande)
        if mom["m00"] > 0:
            cx, cy = int(mom["m10"] / mom["m00"]), int(mom["m01"] / mom["m00"])
            cv2.circle(out, (cx, cy), 30, (255, 255, 255), -1)
            cv2.circle(out, (cx, cy), 30, tuple(int(c) for c in colore), 5)
            testo = str(n)
            (tw, th), _ = cv2.getTextSize(testo, cv2.FONT_HERSHEY_SIMPLEX, 1.1, 3)
            cv2.putText(out, testo, (cx - tw // 2, cy + th // 2), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (30, 30, 30), 3,
                        cv2.LINE_AA)
    return out


def _rifinisci(originale, rett_mask):
    """Dentro il riquadro, separa l'oggetto dallo sfondo (GrabCut) per non incollare pezzi di muro."""
    ys, xs = np.nonzero(rett_mask)
    if len(xs) < 50:
        return rett_mask
    x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    # elementi a cavallo del bordo del 360 o enormi: si usa il riquadro così com'è
    if x1 - x0 > originale.shape[1] * 0.4:
        return rett_mask
    pad = 12
    X0, Y0 = max(0, x0 - pad), max(0, y0 - pad)
    X1, Y1 = min(originale.shape[1], x1 + pad), min(originale.shape[0], y1 + pad)
    ritaglio = originale[Y0:Y1, X0:X1]
    gc = np.full(ritaglio.shape[:2], cv2.GC_BGD, np.uint8)
    gc[rett_mask[Y0:Y1, X0:X1] > 0] = cv2.GC_PR_FGD
    try:
        cv2.grabCut(ritaglio, gc, None, np.zeros((1, 65), np.float64), np.zeros((1, 65), np.float64), 4,
                    cv2.GC_INIT_WITH_MASK)
    except cv2.error:
        return rett_mask
    fg = np.isin(gc, (cv2.GC_FGD, cv2.GC_PR_FGD)).astype(np.uint8)
    # se GrabCut ha tolto quasi tutto, meglio il riquadro
    if fg.sum() < 0.25 * (rett_mask[Y0:Y1, X0:X1] > 0).sum():
        return rett_mask
    out = np.zeros_like(rett_mask)
    out[Y0:Y1, X0:X1] = fg & (rett_mask[Y0:Y1, X0:X1] > 0)
    return out


def maschera_protetta(elementi, maschere, larghezza, altezza, margine=0.006, solo_bloccati=False):
    """Zona da proteggere durante la generazione: tutti gli elementi fissi (un po' allargati)."""
    totale = np.zeros((altezza, larghezza), np.uint8)
    for e in elementi:
        if solo_bloccati and not e.get("blocca_pixel"):
            continue
        if e["categoria"] == "fisso" and e["id"] in maschere:
            totale |= cv2.resize(maschere[e["id"]], (larghezza, altezza), interpolation=cv2.INTER_NEAREST)
    k = max(3, int(larghezza * margine))
    return cv2.dilate(totale, np.ones((k, k), np.uint8))


def _somiglianza(a, b, zona):
    """Quanto due immagini coincidono nella zona (correlazione dei contorni, da -1 a 1)."""
    def contorni(img):
        g = cv2.GaussianBlur(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32), (0, 0), 1.5)
        gx, gy = cv2.Sobel(g, cv2.CV_32F, 1, 0), cv2.Sobel(g, cv2.CV_32F, 0, 1)
        return cv2.GaussianBlur(np.hypot(gx, gy), (0, 0), 2)
    ga, gb = contorni(a)[zona], contorni(b)[zona]
    if ga.size < 50 or ga.std() < 1e-3 or gb.std() < 1e-3:
        return 0.0
    return float(np.corrcoef(ga, gb)[0, 1])


def blocca_elementi_fissi(originale_equi, generato, elementi, maschere, cartella=None, soglia=0.75):
    """Rimette i pixel originali sugli elementi fissi con blocca_pixel=True, ma SOLO se nel generato
    l'elemento è ancora nello stesso punto (altrimenti si creerebbero doppioni). Corregge anche
    la luminosità dei pixel incollati per accordarli alla nuova luce. Restituisce (immagine, rapporto)."""
    from .p4_equirect import _allinea   # import qui per evitare un ciclo tra moduli
    h, w = generato.shape[:2]
    orig = cv2.resize(originale_equi, (w, h), interpolation=cv2.INTER_AREA)
    zona_fissi = maschera_protetta(elementi, maschere, w, h, solo_bloccati=True) > 0
    if zona_fissi.any():
        generato = _allinea(orig, generato, zona_fissi)
    totale = np.zeros((h, w), np.float32)
    corretto = orig.astype(np.float32)
    rapporto = []
    for e in elementi:
        if e["categoria"] != "fisso" or not e.get("blocca_pixel") or e["id"] not in maschere:
            continue
        m = cv2.resize(maschere[e["id"]], (w, h), interpolation=cv2.INTER_NEAREST)
        if not m.any():
            continue
        m = _rifinisci(orig, m)
        zona = m > 0
        simile = _somiglianza(orig, generato, zona)
        if simile < soglia:
            rapporto.append({"id": e["id"], "nome": e["nome"], "incollato": False, "somiglianza": round(simile, 2)})
            continue
        # luce: guadagno per canale calcolato su un anello attorno all'elemento
        anello = (cv2.dilate(m, np.ones((25, 25), np.uint8)) > 0) & ~zona
        if anello.sum() > 100:
            guadagno = np.clip(generato[anello].mean(axis=0) / np.maximum(orig[anello].mean(axis=0), 1), 0.75, 1.35)
            corretto[zona] = np.clip(orig[zona] * guadagno, 0, 255)
        totale = np.maximum(totale, m.astype(np.float32))
        rapporto.append({"id": e["id"], "nome": e["nome"], "incollato": True, "somiglianza": round(simile, 2)})
    if cartella is not None:
        import json
        (cartella / "blocco_fissi.json").write_text(json.dumps(rapporto, indent=2, ensure_ascii=False),
                                                     encoding="utf-8")
    if not totale.any():
        return generato, rapporto
    peso = cv2.GaussianBlur(totale, (0, 0), 2.5)[..., None]
    risultato = (corretto * peso + generato * (1 - peso)).astype(np.uint8)
    return risultato, rapporto


def disegno_linee(equi, larghezza, altezza):
    """Disegno a linee della struttura (muri, porte, finestre) da dare al modello come guida."""
    img = cv2.resize(equi, (larghezza, altezza), interpolation=cv2.INTER_AREA)
    grigio = cv2.GaussianBlur(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), (5, 5), 0)
    bordi = cv2.Canny(grigio, 60, 160)
    n, etichette, stat, _ = cv2.connectedComponentsWithStats(bordi, connectivity=8)
    lunghi = np.zeros_like(bordi)
    soglia = larghezza * 0.03
    for i in range(1, n):
        if max(stat[i, cv2.CC_STAT_WIDTH], stat[i, cv2.CC_STAT_HEIGHT]) >= soglia:
            lunghi[etichette == i] = 255
    lunghi = cv2.dilate(lunghi, np.ones((3, 3), np.uint8))
    return cv2.cvtColor(255 - lunghi, cv2.COLOR_GRAY2BGR)   # linee nere su bianco
