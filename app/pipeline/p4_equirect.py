"""
Passo 4 (metodo principale) - Ristrutturazione del 360 intero in UNA sola immagine.

Perché: generando vista per vista, il modello cambia leggermente l'inquadratura di ogni vista
e i pezzi non combaciano (mobili doppi, effetto fantasma). Lavorando sull'equirettangolare intero
la stanza è una sola, coerente, e la geometria resta al suo posto.

Poi si sistemano i due punti deboli di un 360:
- la GIUNTURA dove il bordo destro si richiude sul sinistro (es. divano tagliato a metà);
- i POLI (soffitto e pavimento sotto il treppiede).
"""
import cv2
import numpy as np

from ..servizi.api import modifica_immagine
from .geometria import estrai_vista, proietta_vista_su_equi

PROMPT_360 = """This image is a full 360-degree EQUIRECTANGULAR panorama (2:1) of one real room, shot from a single point.
Renovate the room according to the specification below and return the SAME equirectangular panorama.

STRICT GEOMETRY RULES:
- Keep the exact equirectangular projection and the exact camera position: every wall edge, corner, ceiling line,
  window, door and French door must stay at the same pixel position. Straight lines stay curved exactly as now.
- The left and right borders of the image join each other (360 wrap): keep them continuous.
- The top row is the ceiling zenith and the bottom row is the floor nadir: keep them stretched as in a real panorama.
- Do not add, remove or move any opening. Elements that must not move: {fissi}.
- Corridors, passages, the entrance door and every door must stay IDENTICAL: same shape, same width,
  same depth and the same view through them. Do not invent new corridors, rooms or doors.
- Keep walls, pillars, curved walls, soffits, beams, radiators, air conditioner and sockets where they are.
  Only finishes, furniture, decor and lighting fixtures change.
- Walls stay smooth, flat, painted walls: no wood slats, no panelling, no niches, no new pilasters,
  no false ceilings or coves, no curved surfaces that were not there (unless the specification asks for them).
- The ceiling stays flat exactly as now.
{modalita}
- Furniture must be complete, realistic and sensibly placed: nothing cut in half, nothing floating.
- Everything is geometrically correct in 3D: rugs are flat true rectangles (or true circles) lying on the floor,
  with straight edges and square corners; furniture, tables, sofas and floor tile joints are straight and regular.
  In the equirectangular image they may look curved ONLY by the exact panorama projection, like the walls do:
  never wavy, bent, melted or distorted.
- Remove the tripod at the bottom: continuous new floor there.

STYLE SPECIFICATION:
{capitolato}

Photorealistic high-end architectural interior photography, natural daylight from the real windows plus warm
3500-4000K light. No people, no text, no logos, no watermark."""

REGOLE_MODALITA = {
    "rinnova": """- FURNITURE LAYOUT STAYS THE SAME: every existing large piece of furniture is replaced by a modern
  high-end equivalent with the SAME footprint, SAME position, SAME size and the same outline in the image
  (the table stays a table of the same size in the same place, chairs where the chairs are, cabinets where the
  cabinets are). Do not add large pieces where there were none and do not remove large pieces.
  Remove only clutter, tablecloths, ornaments, old pictures and personal items.""",
    "potenziale": """- You may rearrange the furniture to show the potential of the room, using simple regular shapes.
  Keep the floor directly under and around the camera free of furniture (about 1 metre radius).""",
}

PROMPT_GIUNTURA = """This is a 360-degree equirectangular panorama of a renovated room. The vertical band in the CENTER
of the image (the transparent area of the mask) contains a seam where two halves of the panorama meet badly:
furniture, rugs or decor may be cut, doubled or not matching.
Repaint ONLY that central band so that everything crossing it is complete, continuous and sensible
(a sofa must be one whole sofa, a rug one whole rug, the floor pattern continuous).
Keep everything outside the band exactly as it is, same projection, same positions, same light.
Inside the band keep every architectural element and fixed device exactly where it is: wall corners, curved walls,
doors, windows, radiators, AIR CONDITIONER units, sockets. Fixed elements: {fissi}.
Only furniture, rugs, decor and floor pattern may be completed or redrawn.
Rugs are flat true rectangles with straight edges, furniture is straight and regular in 3D: they look curved only
by the panorama projection, never wavy or distorted.
STYLE: {capitolato}
No people, no text."""

PROMPT_POLO = """This is a straight-{direzione} view of a renovated room (camera pointing {direzione}), wide angle.
Repaint ONLY the central circular area (the transparent area of the mask) so that it continues the {superficie}
around it seamlessly: same material, same pattern direction, same light. {extra}
If the edge of a piece of furniture or a rug enters the circle, complete it straight and coherent with what is
outside; never invent new objects inside the circle.
Keep everything outside the circle exactly as it is. No people, no text, no objects that are cut."""

STIMA_EURO_360 = {"low": 0.01, "medium": 0.04, "high": 0.12, "xhigh": 0.25, "max": 0.40, "auto": 0.12}


def dimensione_360(larghezza_max=3840):
    """Misura massima supportata per un 360 (lato lungo <= 3840, multipli di 16)."""
    w = min(larghezza_max, 3840) // 32 * 32
    return w, w // 2


def _allinea(riferimento, generata, zona_valida):
    """Il modello a volte sposta di qualche pixel l'immagine: la riallinea all'originale
    usando solo la zona che doveva restare invariata."""
    a = cv2.cvtColor(riferimento, cv2.COLOR_BGR2GRAY).astype(np.float32)
    b = cv2.cvtColor(generata, cv2.COLOR_BGR2GRAY).astype(np.float32)
    w = np.eye(2, 3, dtype=np.float32)
    try:
        _, w = cv2.findTransformECC(a, b, w, cv2.MOTION_AFFINE,
                                    (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 200, 1e-5),
                                    zona_valida.astype(np.uint8), 5)
    except cv2.error:
        return generata
    return cv2.warpAffine(generata, w, (generata.shape[1], generata.shape[0]),
                          flags=cv2.INTER_LANCZOS4 | cv2.WARP_INVERSE_MAP, borderMode=cv2.BORDER_REPLICATE)


def _cucitura_ottimale(a, b, x0, x1):
    """Trova, tra le colonne x0 e x1, il percorso dall'alto in basso dove le immagini a e b
    si somigliano di più (programmazione dinamica). Restituisce la colonna scelta per ogni riga."""
    diff = np.abs(a[:, x0:x1].astype(np.float32) - b[:, x0:x1].astype(np.float32)).sum(axis=2)
    diff = cv2.GaussianBlur(diff, (0, 0), 2)
    h, n = diff.shape
    costo = diff.copy()
    for y in range(1, h):
        prec = costo[y - 1]
        migliore = np.minimum(prec, np.minimum(np.r_[np.inf, prec[:-1]], np.r_[prec[1:], np.inf]))
        costo[y] += migliore
    percorso = np.empty(h, np.int32)
    percorso[-1] = int(np.argmin(costo[-1]))
    for y in range(h - 2, -1, -1):
        c = percorso[y + 1]
        lo, hi = max(0, c - 1), min(n, c + 2)
        percorso[y] = lo + int(np.argmin(costo[y, lo:hi]))
    return percorso + x0


def testo_mappa(elementi):
    """La mappa della stanza (confermata dal fotografo) scritta per il modello immagini."""
    gruppi = {"fisso": [], "rinnova": [], "togli": []}
    for e in elementi or []:
        gruppi.get(e["categoria"], []).append(e["descrizione_en"])
    righe = []
    if gruppi["fisso"]:
        righe.append("FIXED - must stay exactly identical, same position, size and look:\n- "
                     + "\n- ".join(gruppi["fisso"]))
    if gruppi["rinnova"]:
        righe.append("RENEW - same position, same footprint and size, replaced by a modern version following the "
                     "style specification:\n- " + "\n- ".join(gruppi["rinnova"]))
    if gruppi["togli"]:
        righe.append("REMOVE - delete completely, fill with the renovated wall/floor behind:\n- "
                     + "\n- ".join(gruppi["togli"]))
    return "\n".join(righe)


def genera_360(equi, analisi, ai, registro, cartella, istruzioni_extra="", numero=1, modalita="rinnova",
               elementi=None, guida_linee=None, protetta=None):
    """Ristruttura l'intero 360 in una sola chiamata. Restituisce l'equirettangolare generato.
    guida_linee: disegno a linee della struttura (stessa proiezione), passato come seconda immagine."""
    w, h = dimensione_360(ai.get("larghezza_360", 3840))
    ingresso = cv2.resize(equi, (w, h), interpolation=cv2.INTER_AREA)
    prompt = PROMPT_360.format(fissi="; ".join(analisi.elementi_fissi), capitolato=analisi.capitolato_stile,
                               modalita=REGOLE_MODALITA.get(modalita, REGOLE_MODALITA["rinnova"]))
    mappa = testo_mappa(elementi)
    if mappa:
        prompt += "\n\nROOM MAP (confirmed by the photographer):\n" + mappa
    immagini = [ingresso]
    if guida_linee is not None:
        immagini.append(cv2.resize(guida_linee, (w, h), interpolation=cv2.INTER_AREA))
        prompt += ("\n\nThe SECOND image is a black line drawing of the room's structure in the same projection "
                   "(walls, openings, kitchen and furniture outlines). It is NOT a style reference: it shows where "
                   "the lines are. Keep every structural line exactly where it is in the output.")
    if istruzioni_extra:
        prompt += "\n\nIMPORTANT CORRECTIONS (a previous attempt had these problems, avoid them):\n" + istruzioni_extra
    (cartella / f"prompt_360_tentativo{numero}.txt").write_text(prompt, encoding="utf-8")
    qualita = ai.get("qualita_360", "high")
    registro.controlla(STIMA_EURO_360.get(qualita, 0.2), "360 intero")
    maschera = None
    if protetta is not None and protetta.any():
        # maschera OpenAI: opaco = lascia com'è (elementi fissi), trasparente = ristruttura
        p = cv2.resize(protetta, (w, h), interpolation=cv2.INTER_NEAREST)
        maschera = np.dstack([ingresso, (p > 0).astype(np.uint8) * 255])
        prompt += ("\n\nThe mask protects the FIXED elements (doors, corridor, windows, radiators, air conditioner): "
                   "they are already final. Renovate everything else around them and match their position and light.")
    out = modifica_immagine(immagini, prompt, maschera, ai["modello_immagini"], None, qualita, registro,
                            f"Ristrutturazione 360 intero {w}x{h}", dimensione=f"{w}x{h}")
    out = cv2.resize(out, (w, h), interpolation=cv2.INTER_LANCZOS4)
    cv2.imwrite(str(cartella / f"360_generato_tentativo{numero}.png"), out)
    return out


def correggi_giuntura(equi, analisi, ai, registro, cartella, larghezza_fascia=0.16):
    """Ruota il 360 di mezzo giro (la giuntura finisce al centro), ridipinge solo la fascia
    centrale e rimette tutto al suo posto."""
    h, w = equi.shape[:2]
    ruotato = np.roll(equi, w // 2, axis=1)
    fascia = int(w * larghezza_fascia / 2)
    centro = w // 2
    maschera = np.full((h, w), 255, np.uint8)
    maschera[:, centro - fascia:centro + fascia] = 0                 # 0 = da ridipingere
    prompt = PROMPT_GIUNTURA.format(capitolato=analisi.capitolato_stile, fissi="; ".join(analisi.elementi_fissi))
    qualita = ai.get("qualita_360", "high")
    registro.controlla(STIMA_EURO_360.get(qualita, 0.2), "correzione giuntura")
    out = modifica_immagine([ruotato], prompt, np.dstack([ruotato, maschera]), ai["modello_immagini"], None,
                            qualita, registro, "Correzione giuntura 360", dimensione=f"{w}x{h}")
    out = cv2.resize(out, (w, h), interpolation=cv2.INTER_LANCZOS4)
    out = _allinea(ruotato, out, maschera > 0)
    # Dove incollare: non un taglio dritto (taglierebbe tappeti e mobili che escono dalla fascia),
    # ma una "cucitura ottimale" che passa dove nuovo e vecchio sono uguali (es. pavimento libero).
    margine = int(w * 0.10)
    sinistra = _cucitura_ottimale(ruotato, out, centro - fascia - margine, centro - fascia)
    destra = _cucitura_ottimale(ruotato, out, centro + fascia, centro + fascia + margine)
    x = np.arange(w)[None, :]
    dentro = ((x >= sinistra[:, None]) & (x <= destra[:, None])).astype(np.float32)
    peso = cv2.GaussianBlur(dentro, (0, 0), 3)[..., None]
    unito = (out * peso + ruotato * (1 - peso)).astype(np.uint8)
    risultato = np.roll(unito, -(w // 2), axis=1)
    cv2.imwrite(str(cartella / "360_giuntura_corretta.png"), risultato)
    return risultato


def correggi_polo(equi, polo, analisi, ai, registro, cartella, raggio=0.30, lato=1024, fov=120):
    """Ridipinge il centro della vista soffitto (polo='zenit') o pavimento (polo='nadir')
    e lo reinserisce nel 360 con bordi sfumati."""
    h, w = equi.shape[:2]
    pitch = 90 if polo == "zenit" else -90
    vista = estrai_vista(equi, 0, pitch, fov, lato)
    yy, xx = np.mgrid[:lato, :lato]
    distanza = np.hypot(xx - lato / 2, yy - lato / 2) / lato
    maschera = np.where(distanza < raggio, 0, 255).astype(np.uint8)
    if polo == "zenit":
        prompt = PROMPT_POLO.format(direzione="up", superficie="ceiling",
                                    extra="Keep existing ceiling lights only if already fully visible.")
    else:
        prompt = PROMPT_POLO.format(direzione="down", superficie="floor",
                                    extra="Remove any tripod, shadow or camera part: clean continuous floor.")
    registro.controlla(0.08, f"correzione {polo}")
    out = modifica_immagine([vista], prompt, np.dstack([vista, maschera]), ai["modello_immagini"], lato,
                            ai.get("qualita_poli", "medium"), registro, f"Correzione {polo}")
    out = cv2.resize(out, (lato, lato), interpolation=cv2.INTER_LANCZOS4)
    out = _allinea(vista, out, maschera > 0)
    # nella vista: peso 1 dentro il cerchio, sfuma a 0 appena fuori
    peso_vista = np.clip((raggio * 1.15 - distanza) / (raggio * 0.3), 0, 1).astype(np.float32)
    layer, copertura = proietta_vista_su_equi(out, 0, pitch, fov, w, h, potenza_peso=0)
    peso_equi, _ = proietta_vista_su_equi(peso_vista, 0, pitch, fov, w, h, potenza_peso=0)
    peso_equi = (np.clip(peso_equi, 0, 1) * (copertura > 0))[..., None]
    risultato = (layer * peso_equi + equi * (1 - peso_equi)).astype(np.uint8)
    cv2.imwrite(str(cartella / f"360_{polo}_corretto.png"), risultato)
    return risultato
