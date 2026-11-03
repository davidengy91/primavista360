"""
Generazione GUIDATA dal rilievo (metodo attuale).

A ChatGPT non va mai solo la foto: ogni richiesta contiene
  immagine 1 = il 360 vero (in bolla),
  immagine 2 = la guida "radar" (mobili come box a misura reale con etichette, griglia 50 cm,
               elementi fissi in rosso "NON SPOSTARE"),
  + un prompt strutturato compilato in automatico dal rilievo (room.json) e dalla richiesta,
  + una maschera che protegge porte, finestre e gli altri elementi fissi.

Dopo la generazione (tutto senza AI, gratis):
  1. il risultato viene riportato a 2:1 esatto;
  2. controllo dei bordi: le linee della stanza e degli elementi fissi devono coincidere con la foto vera
     (punteggio di fedeltà + immagine di controllo con i bordi originali in rosso);
  3. riallineamento e, dove porte/finestre combaciano, si rimettono i pixel originali;
  4. giunzione 0°/360°: si corregge solo se i bordi non combaciano (circa 0,09 €);
  5. nadir: resta quello della foto (disco col logo solo se esiste config/logo.png);
  6. JPG alla risoluzione originale con metadati 360.
"""
import json
import logging
import math
import os
import time
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
from PIL import Image, ImageDraw

from ..servizi.api import modifica_immagine
from ..servizi.costi import BudgetSuperato, RegistroCosti
from .geometria import estrai_vista, metti_in_bolla, proietta_vista_su_equi
from .p3_guida import _font, _maschere_fissi, _spigoli_stanza, guida_controllo, guida_pulita, ray_casting
from .p3_mappa import _somiglianza
from .p3_stanza import costruisci, serializza
from .p4_equirect import _allinea, correggi_giuntura
from .p7_output import salva_jpg_360

RADICE = Path(__file__).resolve().parents[2]
log = logging.getLogger("primavista")

LARGHEZZA = 3840                     # massimo lato supportato dal modello immagini
STIMA_EURO = 0.15                    # stima prudente di una generazione (serve solo per il tetto di spesa)

FASI = {
    "preparazione": "Preparazione foto e guida",
    "ristrutturazione": "Ristrutturazione con ChatGPT",
    "controllo": "Controllo bordi e allineamento",
    "giunzione": "Giunzione 0°/360° e nadir",
    "consegna": "Preparazione consegna",
}

CORREZIONI = {
    "dimensioni": "Hai cambiato la dimensione della stanza: rifallo identico all'immagine 2, cambia solo arredo e finiture.",
    "aperture": "La porta/finestra si è spostata: rimettila esattamente come nell'immagine 2.",
    "griglia": "Hai copiato la griglia/le etichette della guida: toglile.",
    "misure_mobili": "Un mobile è troppo grande: deve avere la misura del suo blocco nella guida.",
    "oggetti": "Sono comparsi quadri/oggetti non richiesti: toglili, pareti pulite.",
    "pavimento": "Il pavimento non è cambiato: mettilo come richiesto nel capitolato.",
    "bordi": "I bordi destro e sinistro non combaciano: sistemali.",
}

NOMI_PARETI = {"sinistra": "parete sinistra", "destra": "parete destra", "dietro": "parete alle spalle",
               "fondo": "parete di fondo"}


# ------------------------------------------------------------------ prompt strutturato

def _parete_vicina(s, m):
    cx, cz = m["centro_m"]
    distanze = {"sinistra": cx - s["XL"], "destra": s["XR"] - cx, "dietro": cz - s["ZB"], "fondo": s["ZW"] - cz}
    parete = min(distanze, key=distanze.get)
    return parete, distanze[parete]


def _descrivi_mobile(s, m):
    nome = m.get("nome", "mobile")
    if m.get("forma") == "cilindro":
        misure = f"Ø{round(m['L'] * 100)} cm, h {round(m['A'] * 100)} cm"
    elif m["A"] < 0.05:
        misure = f"{round(m['L'] * 100)}×{round(m['P'] * 100)} cm"
    else:
        misure = f"{round(m['L'] * 100)}×{round(m['P'] * 100)} cm, h {round(m['A'] * 100)} cm"
    parete, dist = _parete_vicina(s, m)
    vicini = [f["nome"].lower() for f in s["fissi"] if f["parete"] == parete]
    if dist < max(m["P"], m["L"]) / 2 + 0.15:
        posizione = f"contro la {NOMI_PARETI[parete]}" + (f" (quella con {', '.join(vicini)})" if vicini else "")
    else:
        posizione = f"a {dist:.1f} m dalla {NOMI_PARETI[parete]}"
    return f"- {nome}: {misure}, {posizione}; occupa esattamente il blocco «{nome.upper()}» della guida"


# superfici della stanza: nome per il prompt e lettera della parete sulla guida
PARETI_LETTERE = {"parete_fondo": "A", "parete_destra": "B", "parete_dietro": "C", "parete_sinistra": "D"}
SUPERFICI = {
    "pavimento": "il pavimento",
    "pareti": "tutte le pareti (porte, finestre, termosifoni e prese restano)",
    "parete_fondo": "solo la PARETE A della guida",
    "parete_destra": "solo la PARETE B della guida",
    "parete_dietro": "solo la PARETE C della guida",
    "parete_sinistra": "solo la PARETE D della guida",
    "rivestimento": "il rivestimento delle pareti fino a {altezza} cm da terra",
    "soffitto": "il soffitto",
    "porte": "le porte interne (stessa posizione e misura, cambia modello e finitura)",
}


def _superficie(r):
    return SUPERFICI.get(r["destinazione"], "").format(altezza=r.get("altezza_cm") or 120)


def testo_riferimenti(riferimenti, primo_indice):
    """Elenco delle immagini allegate (prodotti reali e materiali) per il prompt."""
    if not riferimenti:
        return ""
    righe = []
    for i, r in enumerate(riferimenti, primo_indice):
        nota = f" Nota: {r['nota']}." if r.get("nota") else ""
        if r["destinazione"] == "mobile":
            righe.append(f"- Immagine {i}: il prodotto VERO da mettere al posto del blocco «{r['mobile'].upper()}». "
                         f"Riproducilo fedelmente (forma, proporzioni, colore, materiali, finiture, dettagli) "
                         f"con la misura del blocco della guida.{nota}")
        elif r["destinazione"] == "pavimento":
            righe.append(f"- Immagine {i}: il materiale VERO del pavimento: stesso colore, venatura, formato e posa, "
                         f"in scala reale (griglia della guida = 50 cm).{nota}")
        elif r["destinazione"] in SUPERFICI:
            righe.append(f"- Immagine {i}: il materiale/finitura VERO per {_superficie(r)}: stesso colore, disegno, "
                         f"formato e posa, in scala reale (griglia della guida = 50 cm).{nota}")
        else:
            righe.append(f"- Immagine {i}: moodboard di riferimento per palette, stile e atmosfera.{nota}")
    return ("\n\nPRODOTTI E MATERIALI REALI ALLEGATI (hanno la precedenza sul capitolato):\n" + "\n".join(righe) +
            "\nNon copiare sfondi, scritte o loghi delle foto dei prodotti: usa solo il prodotto o il materiale.")


def componi_prompt(s, richiesta, correzione="", riferimenti=None):
    mobili = "\n".join(_descrivi_mobile(s, m) for m in s["mobili"]) or \
        "- nessun mobile nuovo: rinnova solo finiture, pavimento, pareti e luci"
    fissi = ", ".join(f["nome"].lower() for f in s["fissi"]) or "porte, finestre, termosifoni, condizionatore e prese"
    testo = f"""Ti allego due immagini dello stesso 360 equirettangolare.
Immagine 1: la stanza reale. Immagine 2: la guida di progetto con i mobili come blocchi colorati e la griglia a pavimento da 50 cm.

Rendi l'immagine 1 ristrutturata e arredata seguendo ESATTAMENTE la guida:
{mobili}

CAPITOLATO (pavimento, pareti, materiali, colori, luce) richiesto dal cliente:
{richiesta}
Luce: naturale dalle finestre, luci calde 3500K, stile progettato da interior designer, palette coerente.
Un solo pattern forte per ambiente, pareti calme.

OBBLIGATORIO: stessa stanza, stesse dimensioni e proporzioni, stesso punto di vista e stessa altezza camera.
Non spostare né modificare: {fissi}. Le pareti restano dove sono. I mobili hanno la misura dei blocchi della guida.
Non copiare nel risultato la griglia, le etichette o i colori dei blocchi.
Nessun testo, nessuna persona. Output: 360 equirettangolare 2:1 con bordi destro e sinistro che combaciano, fotorealistico."""
    testo += testo_riferimenti(riferimenti, 4 if correzione else 3)
    if correzione:
        testo = ("L'immagine 1 è il tuo risultato precedente, l'immagine 2 è la stanza reale, l'immagine 3 è la guida.\n"
                 f"CORREZIONE RICHIESTA: {correzione}\nCorreggi solo questo e mantieni tutto il resto.\n\n"
                 "Riferimento del progetto (stesse regole di prima):\n" + testo.replace("Immagine 1: la stanza reale. Immagine 2: la guida",
                                                                                         "Stanza reale e guida"))
    return testo


# ------------------------------------------------------------------ controlli senza AI

def fedelta_geometrica(originale, risultato, s, rc, cartella, nome="controllo_bordi.jpg"):
    """Bordi della foto vera confrontati col risultato SOLO su elementi fissi e spigoli della stanza.
    Restituisce la percentuale di bordi che coincidono (entro 4 px a 2048) e salva l'immagine di controllo."""
    w = 2048
    h = w // 2
    a = cv2.resize(originale, (w, h), interpolation=cv2.INTER_AREA)
    b = cv2.resize(risultato, (w, h), interpolation=cv2.INTER_AREA)
    zona = np.zeros((h, w), bool)
    for dentro, _ in _maschere_fissi(s, rc):
        zona |= cv2.resize(dentro.astype(np.uint8), (w, h), interpolation=cv2.INTER_NEAREST) > 0
    zona |= cv2.dilate(cv2.resize(_spigoli_stanza(s, rc).astype(np.uint8), (w, h),
                                  interpolation=cv2.INTER_NEAREST), np.ones((9, 9), np.uint8)) > 0
    bordi_a = cv2.Canny(cv2.GaussianBlur(cv2.cvtColor(a, cv2.COLOR_BGR2GRAY), (5, 5), 0), 60, 160)
    bordi_b = cv2.Canny(cv2.GaussianBlur(cv2.cvtColor(b, cv2.COLOR_BGR2GRAY), (5, 5), 0), 40, 120)
    dist = cv2.distanceTransform(255 - bordi_b, cv2.DIST_L2, 3)
    punti = (bordi_a > 0) & zona
    ok = dist[punti] <= 4
    punteggio = float(100 * ok.mean()) if punti.any() else 100.0
    controllo = (b * 0.75).astype(np.uint8)
    yy, xx = np.nonzero(punti)
    spesso = np.ones((2, 2), np.uint8)
    rosso = np.zeros((h, w), np.uint8)
    verde = np.zeros((h, w), np.uint8)
    rosso[yy[~ok], xx[~ok]] = 1                          # bordi di porte/finestre/angoli che NON coincidono
    verde[yy[ok], xx[ok]] = 1                            # quelli che coincidono
    controllo[cv2.dilate(rosso, spesso) > 0] = (40, 40, 230)
    controllo[cv2.dilate(verde, spesso) > 0] = (60, 200, 60)
    cv2.imwrite(str(cartella / nome), controllo, [cv2.IMWRITE_JPEG_QUALITY, 88])
    return round(punteggio, 1)


def rimetti_fissi(originale, risultato, s, rc, soglia=0.75):
    """Riallinea il risultato sull'originale e, sugli elementi fissi che combaciano, rimette i pixel veri."""
    h, w = risultato.shape[:2]
    orig = cv2.resize(originale, (w, h), interpolation=cv2.INTER_AREA)
    maschere = [cv2.resize(d.astype(np.uint8), (w, h), interpolation=cv2.INTER_NEAREST) for d, _ in _maschere_fissi(s, rc)]
    zona = np.zeros((h, w), bool)
    for m in maschere:
        zona |= m > 0
    if zona.any():
        risultato = _allinea(orig, risultato, cv2.dilate(zona.astype(np.uint8), np.ones((25, 25), np.uint8)) > 0)
    peso = np.zeros((h, w), np.float32)
    rapporto = []
    for f, m in zip(s["fissi"], maschere):
        if not m.any():
            continue
        simile = _somiglianza(orig, risultato, m > 0)
        incolla = simile >= soglia and f["tipo"] in ("finestra", "porta-finestra", "porta", "passaggio")
        rapporto.append({"nome": f["nome"], "somiglianza": round(simile, 2), "rimesso_originale": bool(incolla)})
        if incolla:
            peso = np.maximum(peso, m.astype(np.float32))
    if peso.any():
        peso = cv2.GaussianBlur(peso, (0, 0), 2.5)[..., None]
        risultato = (orig * peso + risultato * (1 - peso)).astype(np.uint8)
    return risultato, rapporto


def giunzione_ok(equi, soglia=14.0):
    """True se la colonna 0 e l'ultima combaciano (differenza media bassa)."""
    a = equi[:, :6].astype(np.float32).mean(axis=1)
    b = equi[:, -6:].astype(np.float32).mean(axis=1)
    return float(np.abs(a - b).mean()) < soglia, float(np.abs(a - b).mean())


def disco_nadir(equi, testo="SIMULAZIONE", logo=None, fov=40, lato=1024, raggio=0.46):
    """Copre il treppiede con un disco elegante con la dicitura (o il logo), proiettato esattamente nel 360."""
    h, w = equi.shape[:2]
    vista = Image.new("RGB", (lato, lato), (40, 40, 44))
    d = ImageDraw.Draw(vista)
    if logo and Path(logo).exists():
        lg = Image.open(logo).convert("RGBA")
        lg.thumbnail((int(lato * 0.6), int(lato * 0.6)))
        vista.paste(lg, ((lato - lg.width) // 2, (lato - lg.height) // 2), lg)
    else:
        d.text((lato / 2, lato / 2 - 30), testo, fill=(245, 245, 245), font=_font(lato // 11), anchor="mm")
        d.text((lato / 2, lato / 2 + 60), "PrimaVista 360", fill=(200, 180, 150), font=_font(lato // 22), anchor="mm")
    vista = cv2.cvtColor(np.array(vista), cv2.COLOR_RGB2BGR)   # il "sopra" della vista è la direzione frontale
    yy, xx = np.mgrid[:lato, :lato]
    r = np.hypot(xx - lato / 2, yy - lato / 2) / lato
    peso_vista = np.clip((raggio - r) / 0.01, 0, 1).astype(np.float32)
    layer, copertura = proietta_vista_su_equi(vista, 0, -90, fov, w, h, potenza_peso=0)
    peso, _ = proietta_vista_su_equi(peso_vista, 0, -90, fov, w, h, potenza_peso=0)
    peso = (np.clip(peso, 0, 1) * (copertura > 0))[..., None]
    return (layer * peso + equi * (1 - peso)).astype(np.uint8)


# ------------------------------------------------------------------ generazione completa

PROMPT_RIPROGETTA = """
NUOVA DISPOSIZIONE: togli TUTTI i mobili e gli oggetti che ci sono ora nella stanza.
I mobili nuovi stanno SOLO nei blocchi colorati della guida, nella posizione e con la misura dei blocchi:
nessun altro mobile, nessun mobile dove la guida non ne mette."""

PROMPT_ARREDA = """
HOME STAGING DI UNA STANZA VUOTA: aggiungi SOLO i mobili dei blocchi colorati della guida, nella posizione e con la
misura dei blocchi, più pochi complementi coerenti (tende, lampade, una pianta, un quadro sobrio).
Pavimento, pareti, soffitto, porte e finestre restano quelli della foto, salvo diversa indicazione nel capitolato.
Ogni mobile appoggia correttamente a terra, con ombre di contatto realistiche e luce coerente con le finestre."""

PROMPT_PRODOTTO = """Ti allego due immagini dello stesso 360 equirettangolare.
Immagine 1: la stanza reale. Immagine 2: la guida con la posizione esatta di ciò che va provato.
Modifica SOLO l'area trasparente della maschera, tutto il resto deve restare identico.

DA PROVARE NELLA STANZA:
{elementi}

{richiesta}
Gli oggetti vecchi indicati da sostituire (es. il divano attuale) vanno tolti del tutto e sostituiti.
Quando cambia una SUPERFICIE (pavimento, pareti, rivestimento, soffitto), i mobili che ci stanno davanti o sopra
restano esattamente com'erano: cambia solo la superficie visibile, con posa e fughe in scala reale.
Il prodotto è appoggiato correttamente (a terra o a parete), con la misura del suo blocco nella guida, con ombre,
riflessi e luce coerenti con la stanza reale. Se nell'area c'è un oggetto vecchio, sostituiscilo o toglilo.
Non copiare nel risultato la griglia, le etichette o i colori dei blocchi. Nessun testo, nessuna persona.
Output: lo stesso 360 equirettangolare 2:1, fotorealistico."""


NOMI_COLORI = ["blu", "verde", "rosa", "arancione", "viola", "giallo", "rosso", "verde scuro"]   # come COLORI_MOBILI

PROMPT_PIANTINA = """Ti allego la BASE GEOMETRICA di un 360 equirettangolare: una stanza calcolata IN SCALA dalla pianta.
È un lavoro di RENDERING, non di creazione: trasformala in una foto 360 fotorealistica della STESSA stanza.

Significato dei colori della base:
- grigi = pareti (le linee scure sono gli angoli tra le pareti); bianco in alto = soffitto; grigio chiaro in basso = pavimento;
- azzurro = finestre e porte-finestre (vetri con luce naturale, esterno luminoso e sfocato);
- marrone = porte interne; grigio scuro = passaggi aperti;
- blocchi colorati = mobili A MISURA: ogni mobile sta esattamente dentro il suo blocco, con la sua forma e misura.

Geometria INVARIATA: stesse pareti, stessi angoli, stessa altezza, porte e finestre nella stessa posizione e misura;
stesso punto di vista; 360 equirettangolare 2:1 con i bordi destro e sinistro che combaciano.

MOBILI:
{mobili}

CAPITOLATO (pavimento, pareti, materiali, colori, stile) richiesto dal cliente:
{richiesta}
Luce naturale dalle finestre, stile progettato da interior designer, palette coerente.
Non aggiungere lampadari o luci se non richiesti. Nessun testo, nessuna scritta, nessuna griglia, nessuna persona.
Fotorealistico, qualità fotografia d'interni."""


def componi_prompt_piantina(s, richiesta, correzione="", riferimenti=None):
    righe = []
    for i, m in enumerate(s["mobili"]):
        righe.append(_descrivi_mobile(s, m) + f" (blocco {NOMI_COLORI[i % len(NOMI_COLORI)]})")
    testo = PROMPT_PIANTINA.format(mobili="\n".join(righe) or "- nessun mobile: stanza vuota rifinita",
                                   richiesta=richiesta or "moderno, luminoso, materiali di qualità")
    if riferimenti:
        testo += "\n\nIMMAGINI ALLEGATE (prodotti e materiali veri):\n" + testo_riferimenti(riferimenti, 3 if correzione else 2)
    if correzione:
        testo = ("L'immagine 1 è il tuo risultato precedente, l'immagine 2 la base geometrica.\n"
                 f"CORREZIONE RICHIESTA: {correzione}\nCorreggi solo questo, il resto resta com'è.\n\n" + testo)
    return testo


def _carica_riferimenti(cartella, s):
    """Foto di prodotti reali e materiali allegate (solo per mobili ancora presenti nel rilievo)."""
    nomi_mobili = {m.get("nome", "") for m in s["mobili"]}
    tutti = json.loads((cartella / "riferimenti.json").read_text(encoding="utf-8")) \
        if (cartella / "riferimenti.json").exists() else []
    return [r for r in tutti if r["destinazione"] != "mobile" or r.get("mobile") in nomi_mobili]


def _maschera_prova(s, rc, riferimenti):
    """Zona da modificare in 'Prova prodotto': i box dei mobili + le superfici con un materiale allegato."""
    zona = np.zeros(rc["t"].shape, np.uint8)
    for i, _ in enumerate(s["mobili"]):
        zona |= (rc["mobile"] == i).astype(np.uint8)
    destinazioni = {r["destinazione"] for r in riferimenti}
    libero = rc["mobile"] < 0
    fissi = np.zeros_like(zona, bool)
    for dentro, _ in _maschere_fissi(s, rc):
        fissi |= dentro
    pareti = (rc["superficie"] >= 2) & libero & ~fissi
    altezza = rc["punto"][..., 1] + s["h"]                       # altezza dal pavimento di ogni punto
    if "pavimento" in destinazioni:
        zona |= ((rc["superficie"] == 0) & libero).astype(np.uint8)
    if "pareti" in destinazioni:
        zona |= pareti.astype(np.uint8)
    for nome, codice in (("parete_sinistra", 2), ("parete_destra", 3), ("parete_dietro", 4), ("parete_fondo", 5)):
        if nome in destinazioni:
            zona |= ((rc["superficie"] == codice) & libero & ~fissi).astype(np.uint8)
    for r in riferimenti:
        if r["destinazione"] == "rivestimento":
            zona |= (pareti & (altezza <= (r.get("altezza_cm") or 120) / 100)).astype(np.uint8)
    if "soffitto" in destinazioni:
        zona |= ((rc["superficie"] == 1) & libero).astype(np.uint8)
    if "porte" in destinazioni:
        for f, (dentro, _) in zip(s["fissi"], _maschere_fissi(s, rc)):
            if f["tipo"] in ("porta", "passaggio"):
                zona |= dentro.astype(np.uint8)
    # un po' più grande: serve spazio per ombre e raccordi
    k = max(9, rc["t"].shape[1] // 160)
    return cv2.dilate(zona, np.ones((k, k), np.uint8))


def _descrivi_prova(s, riferimenti):
    righe = [_descrivi_mobile(s, m) for m in s["mobili"]]
    for r in riferimenti:
        if r["destinazione"] in SUPERFICI:
            righe.append(f"- {_superficie(r)}, nel materiale dell'immagine allegata, in scala reale")
    return "\n".join(righe) or "- (niente di indicato)"


def _incolla_zona(originale, generato, zona):
    """Tiene il generato solo nella zona (riallineato e sfumato): fuori resta l'originale al pixel."""
    generato = _allinea(originale, generato, cv2.erode((zona == 0).astype(np.uint8), np.ones((15, 15), np.uint8)) > 0)
    peso = cv2.GaussianBlur(zona.astype(np.float32), (0, 0), 4)[..., None]
    return (generato * peso + originale * (1 - peso)).astype(np.uint8)


PROMPT_OGGETTO = """Immagine 1: una foto reale di una stanza (vista prospettica normale).
RICHIESTA DEL CLIENTE: {istruzione}
Al centro della foto c'è la zona su cui lavorare ({cosa}).
{prodotto}
Se sostituisci un oggetto, quello vecchio deve sparire del tutto, comprese le sue parti (es. testiera, gambe, maniglie).
Stessa posizione, appoggio corretto (a terra o a parete), prospettiva coerente con la foto e proporzioni realistiche
rispetto alla stanza.
Tutto il resto della stanza resta IDENTICO: stessa inquadratura, stessi mobili, stesse pareti, stessa luce, stessi colori.
Ombre di contatto e riflessi realistici, coerenti con la luce della stanza.
Fotorealistico. Nessun testo, nessuna persona, nessun logo."""


def vista_oggetto(m, W, H):
    """Vista prospettica centrata sull'oggetto (maschera m nel 360): yaw, pitch, fov che lo contengono con contesto."""
    from .geometria import _direzioni_equi
    dx, dy, dz = _direzioni_equi(W, H)
    v = np.array([dx[m].mean(), dy[m].mean(), dz[m].mean()], np.float64)
    v /= np.linalg.norm(v)
    yaw, pitch = math.degrees(math.atan2(v[0], v[2])), math.degrees(math.asin(np.clip(v[1], -1, 1)))
    coseno = np.clip(dx[m] * v[0] + dy[m] * v[1] + dz[m] * v[2], -1, 1)
    apertura = math.degrees(math.acos(float(coseno.min())))
    return yaw, pitch, float(np.clip(2 * apertura * 1.25 + 10, 50, 130))


def area_libera(mv):
    """Dove ChatGPT può lavorare: il riquadro dell'oggetto, più largo e soprattutto più alto
    (testiere, schienali, mensole sopra l'oggetto spesso restano fuori dal riquadro)."""
    lato = mv.shape[0]
    ys, xs = np.nonzero(mv)
    x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    w, h = x1 - x0, y1 - y0
    area = np.zeros(mv.shape, np.uint8)
    area[max(0, int(y0 - 0.6 * h)):min(lato, int(y1 + 0.15 * h)),
         max(0, int(x0 - 0.15 * w)):min(lato, int(x1 + 0.15 * w))] = 1
    return area


def zona_cambiata(vista, gen, mv, area):
    """Cosa ha cambiato davvero ChatGPT: confronto pixel per pixel con la foto (dopo il riallineamento).
    Si tengono solo i cambiamenti attaccati all'oggetto e dentro l'area libera; i buchi si chiudono.
    Così rientrano anche le parti nuove fuori dal riquadro (es. la testiera nuova) e niente altro."""
    lato = vista.shape[0]
    a = cv2.GaussianBlur(vista, (0, 0), 2).astype(np.int16)
    b = cv2.GaussianBlur(gen, (0, 0), 2).astype(np.int16)
    diff = np.abs(a - b).max(axis=2)
    cambiato = ((diff > 30) & (area > 0)).astype(np.uint8)
    k = max(3, lato // 300)
    cambiato = cv2.morphologyEx(cambiato, cv2.MORPH_OPEN, np.ones((k * 2, k * 2), np.uint8))   # via le linee sottili
    cambiato = cv2.morphologyEx(cambiato, cv2.MORPH_CLOSE, np.ones((k * 5, k * 5), np.uint8))
    # solo i pezzi che toccano la zona indicata
    vicino = cv2.dilate(mv.astype(np.uint8), np.ones((lato // 25,) * 2, np.uint8)) > 0
    n, etichette = cv2.connectedComponents(cambiato)
    tenere = np.zeros_like(cambiato)
    for i in range(1, n):
        pezzo = etichette == i
        if (pezzo & vicino).any():
            tenere |= pezzo.astype(np.uint8)
    # solo ciò che è cambiato davvero: dove ChatGPT non ha toccato nulla resta la foto originale (più nitida)
    zona = tenere & area
    # riempie i buchi interni (es. un cuscino uguale al vecchio dentro il letto nuovo)
    contorni, _ = cv2.findContours(zona, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    piena = np.zeros_like(zona)
    cv2.drawContours(piena, contorni, -1, 1, thickness=cv2.FILLED)
    # contorno liscio (niente gradini o frange): sfocatura e soglia
    piena = (cv2.GaussianBlur(cv2.dilate(piena, np.ones((k * 2, k * 2), np.uint8)).astype(np.float32), (0, 0), k * 2) > 0.5)
    return piena.astype(np.uint8) & area


def reinserisci(out, vista, gen, mv, yaw, pitch, fov):
    """Rimette nel 360 la parte cambiata della vista generata, con un bordo stretto (niente aloni sfumati).
    Restituisce il 360 aggiornato e la zona usata (per controllo)."""
    lato = vista.shape[0]
    H, W = out.shape[:2]
    area = area_libera(mv)
    # riallineamento solo se serve davvero (se l'immagine è già allineata, spostarla creerebbe false differenze)
    valido = cv2.erode((area == 0).astype(np.uint8), np.ones((25, 25), np.uint8)) > 0
    scarto = lambda g: float(np.abs(vista.astype(np.int16) - g.astype(np.int16)).max(axis=2)[valido].mean()) if valido.any() else 0
    allineata = _allinea(vista, gen, valido)
    if scarto(allineata) < scarto(gen) - 0.2:
        gen = allineata
    zona = zona_cambiata(vista, gen, mv, area)
    peso_v = cv2.GaussianBlur(zona.astype(np.float32), (0, 0), max(1.0, lato * 0.0015))
    layer, copertura = proietta_vista_su_equi(gen, yaw, pitch, fov, W, H, potenza_peso=0)
    peso, _ = proietta_vista_su_equi(peso_v, yaw, pitch, fov, W, H, potenza_peso=0)
    peso = (np.clip(peso, 0, 1) * (copertura > 0))[..., None]
    return (layer * peso + out * (1 - peso)).astype(np.uint8), zona, gen


def prodotti_da_provare(dati):
    """I prodotti scritti dal cliente nella pagina: [{"nome": "Prodotto 1", "istruzione": "sostituisci il letto…"}]."""
    return [x for x in (dati.get("prodotti") or []) if (x.get("istruzione") or "").strip()]


def _prova_prodotti(base_eq, prodotti, riferimenti, ai, registro, cartella, numero, frase=""):
    """PROVA PRODOTTO senza ritagli: il cliente allega la foto e scrive cosa fare.
    1) Claude trova nella foto la zona (l'oggetto da sostituire o lo spazio dove aggiungere): tutte PRIMA di spendere;
    2) vista prospettica centrata sulla zona; ChatGPT lavora libero in un'area ampia;
    3) torna nel 360 SOLO quello che è cambiato attaccato alla zona: il resto resta la foto originale."""
    from .p9_trova import trova_zona
    H, W = base_eq.shape[:2]
    out = base_eq.copy()
    lato = 1536
    lavori = []
    for k, prod in enumerate(prodotti, 1):
        foto = [r for r in riferimenti if r["destinazione"] == "mobile" and r.get("mobile") == prod["nome"]]
        immagini_prodotto = [cv2.imread(str(cartella / r["file"])) for r in foto]
        m, cosa = trova_zona(base_eq, prod["istruzione"], immagini_prodotto, ai, registro)
        if m is None:
            raise RuntimeError(f"Non ho trovato nella foto dove fare «{prod['istruzione']}» ({cosa}). "
                               "Scrivilo in modo più preciso (es. 'sostituisci il letto matrimoniale con questo').")
        controllo = cv2.resize(base_eq, (1600, 800)).copy()
        controllo[cv2.resize(m.astype(np.uint8), (1600, 800)) == 0] //= 3
        cv2.imwrite(str(cartella / f"zona_prodotto{k}_v{numero}.jpg"), controllo, [cv2.IMWRITE_JPEG_QUALITY, 85])
        lavori.append((k, prod, foto, immagini_prodotto, m, cosa))

    for k, prod, foto, immagini_prodotto, m, cosa in lavori:
        yaw, pitch, fov = vista_oggetto(m, W, H)
        vista = estrai_vista(out, yaw, pitch, fov, lato)
        mv = estrai_vista(m.astype(np.float32), yaw, pitch, fov, lato) > 0.5
        note = "; ".join(r["nota"] for r in foto if r.get("nota"))
        testo_prodotto = ("Usa il prodotto VERO delle immagini allegate (dalla 2 in poi): riproducilo fedelmente, stessa forma, "
                          "proporzioni, colori, materiali e finiture" + (f" ({note})" if note else "") + "."
                          if immagini_prodotto else "")
        istruzione = prod["istruzione"] + (f". CORREZIONE RICHIESTA: {frase}" if frase else "")
        prompt = PROMPT_OGGETTO.format(istruzione=istruzione, cosa=cosa, prodotto=testo_prodotto)
        (cartella / f"prompt_oggetto{k}_v{numero}.txt").write_text(prompt, encoding="utf-8")
        area = area_libera(mv)
        maschera = np.dstack([vista, ((area == 0) * 255).astype(np.uint8)])   # trasparente = dove può lavorare
        registro.controlla(0.12, f"prodotto {k}")
        gen = modifica_immagine([vista] + immagini_prodotto, prompt, maschera, ai["modello_immagini"], lato,
                                ai.get("qualita_360", "high"), registro, f"Prova prodotto {k} v{numero}")
        gen = cv2.resize(gen, (lato, lato), interpolation=cv2.INTER_LANCZOS4)
        out, zona, gen = reinserisci(out, vista, gen, mv, yaw, pitch, fov)
        controllo = gen.copy()
        controllo[zona == 0] = (controllo[zona == 0] * 0.35).astype(np.uint8)   # in scuro: ciò che NON rientra
        cv2.imwrite(str(cartella / f"oggetto{k}_v{numero}.jpg"), np.hstack([vista, gen, controllo]),
                    [cv2.IMWRITE_JPEG_QUALITY, 88])
    return out


def genera(cartella, avanzamento=None, correzione=None, variante=None):
    """Genera (o corregge) il 360 del progetto secondo il servizio scelto:
    rinnova (ristrutturazione, mobili al loro posto), riprogetta (nuova disposizione, varianti A/B/C),
    prodotto (prova di un mobile/materiale: cambia solo quella zona).
    correzione = chiave di CORREZIONI o testo libero."""
    cartella = Path(cartella)
    impostazioni = json.loads((RADICE / "config" / "impostazioni.json").read_text(encoding="utf-8"))
    ai = impostazioni["ai"]
    scheda = json.loads((cartella / "richiesta.json").read_text(encoding="utf-8"))
    servizio = scheda.get("servizio", "rinnova")
    dati = json.loads((cartella / "stanza_input.json").read_text(encoding="utf-8"))
    if variante and (dati.get("varianti") or {}).get(variante) is not None:
        dati["mobili"] = dati["varianti"][variante]
    suf = f"_{variante}" if variante else ""
    registro = RegistroCosti(cartella / "costi.json", os.getenv("SPESA_MASSIMA_EURO", "5"))
    if (cartella / "costi.json").exists():
        registro.chiamate = json.loads((cartella / "costi.json").read_text(encoding="utf-8")).get("chiamate", [])
    t0 = time.time()

    def fase(chiave, testo):
        log.info(">> %s", testo)
        if avanzamento:
            avanzamento(chiave, testo)

    fase("preparazione", "Preparo la foto in bolla e la guida radar")
    prodotti = prodotti_da_provare(dati) if servizio == "prodotto" else []
    s = costruisci(dati)
    if "errore" in s and not prodotti:
        raise RuntimeError(f"Rilievo non valido: {s['errore']}")
    if "errore" in s:
        s = None          # per provare i prodotti il rilievo della stanza non serve
    da_piantina = scheda.get("origine") == "piantina"
    incl = dati.get("inclinazione", {})
    if da_piantina:
        foto = guida_pulita(s, 4096)[0]
    else:
        base = cv2.imread(str(cartella / "originale_ridotto.jpg"))
        foto = metti_in_bolla(base, float(incl.get("pitch", 0)), float(incl.get("roll", 0)))
    foto_g = cv2.resize(foto, (LARGHEZZA, LARGHEZZA // 2), interpolation=cv2.INTER_AREA)
    versioni = sorted(cartella.glob(f"risultato{suf}_v*.jpg"))
    numero = len(versioni) + 1
    frase = CORREZIONI.get(correzione, correzione or "")
    if da_piantina and impostazioni.get("motore3d", {}).get("attivo", True):
        # MOTORE 3D: la stanza e i mobili si costruiscono in Blender dalle misure e si fa il render 360.
        # Niente AI che disegna: le misure e le proporzioni sono quelle del progetto.
        from ..motore3d.render import prepara, render
        fase("ristrutturazione", "Blender costruisce la stanza in 3D e fa il render 360 (circa 1-2 minuti)")
        png = cartella / f"render3d{suf}_v{numero}.png"
        secondi = render(prepara(serializza(s), scheda.get("richiesta", ""), scheda.get("superfici")), png,
                         larghezza=impostazioni.get("motore3d", {}).get("larghezza", 4096),
                         campioni=impostazioni.get("motore3d", {}).get("campioni", 128))
        log.info("Render 3D in %.0f s", secondi)
        out = cv2.imread(str(png))
        return _consegna(cartella, scheda, impostazioni, registro, foto, out, suf, numero, variante, servizio,
                         "", 100.0, [], t0, fase, s=s, ai=ai)
    if prodotti:
        # PROVA PRODOTTO: foto + descrizione del cliente, la zona la trova Claude; il resto resta al pixel
        tutti = json.loads((cartella / "riferimenti.json").read_text(encoding="utf-8")) \
            if (cartella / "riferimenti.json").exists() else []
        base = foto_g
        if frase and versioni:
            base = cv2.resize(cv2.imread(str(versioni[-1])), (LARGHEZZA, LARGHEZZA // 2), interpolation=cv2.INTER_AREA)
        fase("ristrutturazione", f"Claude trova la zona, ChatGPT prova {len(prodotti)} prodott{'o' if len(prodotti) == 1 else 'i'}")
        out = _prova_prodotti(base, prodotti, tutti, ai, registro, cartella, numero, frase)
        fase("controllo", "Controllo: fuori dagli oggetti la foto resta identica")
        cv2.imwrite(str(cartella / f"controllo_bordi{suf}_v{numero}.jpg"), out)
        return _consegna(cartella, scheda, impostazioni, registro, foto, out, suf, numero, variante, servizio,
                         frase, 100.0, [], t0, fase)
    rc = ray_casting(s, LARGHEZZA)
    guida, _ = guida_controllo(s, foto, LARGHEZZA, rc=rc)
    cv2.imwrite(str(cartella / f"guida_inviata{suf}.jpg"), guida, [cv2.IMWRITE_JPEG_QUALITY, 90])
    riferimenti = _carica_riferimenti(cartella, s)
    zona_prova = None
    if servizio == "prodotto":
        zona_prova = _maschera_prova(s, rc, riferimenti)
        if not zona_prova.any():
            raise RuntimeError("Indica cosa provare: aggiungi un mobile oppure allega un materiale (pavimento o pareti).")
    if frase and versioni:
        precedente = cv2.resize(cv2.imread(str(versioni[-1])), (LARGHEZZA, LARGHEZZA // 2), interpolation=cv2.INTER_AREA)
        immagini, prima = [precedente, foto_g, guida], precedente
    else:
        frase, immagini, prima = "", [foto_g, guida], foto_g
    if da_piantina:
        immagini = immagini[:-1]          # da piantina si manda SOLO la base pulita (la guida con le scritte confonde)
    for r in riferimenti:
        immagini.append(cv2.imread(str(cartella / r["file"])))

    if servizio == "prodotto":
        prompt = PROMPT_PRODOTTO.format(elementi=_descrivi_prova(s, riferimenti),
                                        richiesta=("Indicazioni: " + scheda["richiesta"]) if scheda.get("richiesta") else "")
        prompt += testo_riferimenti(riferimenti, 4 if frase else 3)
        if frase:
            prompt = ("L'immagine 1 è il tuo risultato precedente, l'immagine 2 la stanza reale, l'immagine 3 la guida.\n"
                      f"CORREZIONE RICHIESTA: {frase}\nCorreggi solo questo.\n\n" + prompt)
        # maschera: trasparente = zona da modificare, opaco = tutto il resto
        maschera = np.dstack([prima, ((zona_prova == 0) * 255).astype(np.uint8)])
    elif da_piantina:
        prompt = componi_prompt_piantina(s, scheda.get("richiesta", ""), frase, riferimenti)
        maschera = None
    else:
        prompt = componi_prompt(s, scheda.get("richiesta", ""), frase, riferimenti)
        if servizio == "riprogetta":
            prompt += "\n" + PROMPT_RIPROGETTA
        elif servizio == "arreda":
            prompt = prompt.replace("ristrutturata e arredata", "arredata (home staging)") + "\n" + PROMPT_ARREDA
            if not scheda.get("svuotata"):
                prompt += "\n" + PROMPT_RIPROGETTA      # stanza arredata non svuotata: i mobili vecchi vanno tolti
        protetta = np.zeros(rc["t"].shape, np.uint8)
        for dentro, _ in _maschere_fissi(s, rc):
            protetta |= dentro.astype(np.uint8)
        protetta = cv2.dilate(protetta, np.ones((9, 9), np.uint8))
        maschera = np.dstack([prima, protetta * 255]) if protetta.any() and not frase else None
    (cartella / f"prompt{suf}_v{numero}.txt").write_text(prompt, encoding="utf-8")

    testo_fase = {"prodotto": "ChatGPT inserisce il prodotto", "riprogetta": "ChatGPT riprogetta la stanza",
                  "arreda": "ChatGPT arreda la stanza"}.get(
        servizio, "ChatGPT sta ristrutturando il 360")
    fase("ristrutturazione", testo_fase + (f" (variante {variante})" if variante else "") +
         (f" (correzione: {frase[:60]}…)" if frase else ""))
    registro.controlla(STIMA_EURO, "generazione")
    out = modifica_immagine(immagini, prompt, maschera, ai["modello_immagini"], None, ai.get("qualita_360", "high"),
                            registro, f"{servizio.capitalize()} {variante or ''} v{numero}".replace("  ", " "),
                            dimensione=f"{LARGHEZZA}x{LARGHEZZA // 2}")
    out = cv2.resize(out, (LARGHEZZA, LARGHEZZA // 2), interpolation=cv2.INTER_LANCZOS4)   # 2:1 esatto
    cv2.imwrite(str(cartella / f"grezzo{suf}_v{numero}.png"), out)

    fase("controllo", "Controllo dei bordi: porte, finestre e angoli")
    if servizio == "prodotto":
        out = _incolla_zona(prima, out, zona_prova)      # fuori dalla zona resta la foto al pixel
        rapporto_fissi = []
    elif da_piantina:
        rapporto_fissi = []          # non c'è una foto vera da rimettere: solo il controllo dei bordi
    else:
        out, rapporto_fissi = rimetti_fissi(foto_g, out, s, rc)
    fedelta = fedelta_geometrica(foto_g, out, s, rc, cartella, f"controllo_bordi{suf}_v{numero}.jpg")
    log.info("Fedeltà geometrica: %.0f%%", fedelta)

    return _consegna(cartella, scheda, impostazioni, registro, foto, out, suf, numero, variante, servizio,
                     frase, fedelta, rapporto_fissi, t0, fase, s=s, ai=ai)


def _consegna(cartella, scheda, impostazioni, registro, foto, out, suf, numero, variante, servizio, frase, fedelta,
              rapporto_fissi, t0, fase, s=None, ai=None):
    """Giunzione, nadir, nitidezza, salvataggio del JPG 360 e delle anteprime."""
    ai = ai or impostazioni["ai"]
    fase("giunzione", "Giunzione 0°/360° e nadir")
    ok, diff = giunzione_ok(out)
    if not ok and servizio != "prodotto":
        try:
            registro.controlla(0.12, "giunzione")
            adattatore = SimpleNamespace(capitolato_stile=scheda.get("richiesta", ""),
                                         elementi_fissi=[f["nome"] for f in s["fissi"]])
            out = correggi_giuntura(out, adattatore, ai, registro, cartella)
        except BudgetSuperato as e:
            log.warning(str(e))
    logo = RADICE / "config" / "logo.png"
    # niente disco "SIMULAZIONE": il nadir resta quello della foto; il disco si mette solo se c'è il logo PrimaVista
    if logo.exists():
        out = disco_nadir(out, logo=logo)

    fase("consegna", "Salvataggio del JPG 360 con metadati")
    cv2.imwrite(str(cartella / f"risultato{suf}_v{numero}.jpg"), out, [cv2.IMWRITE_JPEG_QUALITY, 92])
    percorso_foto = Path(scheda["foto"])
    originale = cv2.imread(str(percorso_foto))
    h0, w0 = originale.shape[:2]
    finale = None
    if impostazioni["output"].get("nitidezza_ai", True) and w0 > LARGHEZZA:
        try:
            from .p8_modelli import aumenta_nitidezza, disponibili
            if disponibili()["esrgan"]:
                fase("consegna", f"Nitidezza: porto il 360 a {w0} px (circa 1 minuto)")
                finale = aumenta_nitidezza(out, w0)
                if finale.shape[0] != h0:
                    finale = cv2.resize(finale, (w0, h0), interpolation=cv2.INTER_AREA)
        except Exception as e:  # noqa: BLE001  se il modello non va, si ingrandisce in modo classico
            log.warning("Nitidezza AI non riuscita (%s): ingrandimento classico", e)
            finale = None
    if finale is None:
        finale = cv2.resize(out, (w0, h0), interpolation=cv2.INTER_LANCZOS4)
    for nome in {f"risultato_360{suf}.jpg", "risultato_360.jpg"}:
        salva_jpg_360(finale, str(cartella / nome), originale=str(percorso_foto),
                      qualita=impostazioni["output"]["qualita_jpg"])
    vista_dopo = cv2.resize(out, (4096, 2048), interpolation=cv2.INTER_CUBIC)
    for nome in {f"viewer_dopo{suf}.jpg", "viewer_dopo.jpg"}:
        cv2.imwrite(str(cartella / nome), vista_dopo, [cv2.IMWRITE_JPEG_QUALITY, 90])
    cv2.imwrite(str(cartella / "viewer_prima.jpg"), cv2.resize(foto, (4096, 2048)), [cv2.IMWRITE_JPEG_QUALITY, 90])
    cv2.imwrite(str(cartella / "miniatura.jpg"), cv2.resize(out, (800, 400), interpolation=cv2.INTER_AREA))
    cv2.imwrite(str(cartella / f"prima_dopo{suf}.jpg"),
                np.vstack([cv2.resize(foto, (2400, 1200)), cv2.resize(out, (2400, 1200))]), [cv2.IMWRITE_JPEG_QUALITY, 88])
    if suf:
        cv2.imwrite(str(cartella / "prima_dopo.jpg"), cv2.imread(str(cartella / f"prima_dopo{suf}.jpg")))
    # controllo dei bordi: c'è solo quando l'immagine l'ha fatta l'AI (nel render 3D la geometria è già esatta)
    bordi = cv2.imread(str(cartella / f"controllo_bordi{suf}_v{numero}.jpg"))
    if bordi is None:
        bordi = vista_dopo
    for nome in {f"controllo_bordi{suf}.jpg", "controllo_bordi.jpg"}:
        cv2.imwrite(str(cartella / nome), bordi)

    storia = json.loads((cartella / "versioni.json").read_text(encoding="utf-8")) if (cartella / "versioni.json").exists() else []
    storia.append({"versione": numero, "variante": variante, "servizio": servizio, "correzione": frase,
                   "fedelta_geometrica": fedelta, "giunzione_diff": round(diff, 1), "fissi": rapporto_fissi,
                   "ora": time.strftime("%H:%M"), "costo_totale_euro": round(registro.totale_euro(), 2)})
    (cartella / "versioni.json").write_text(json.dumps(storia, indent=2, ensure_ascii=False), encoding="utf-8")
    riepilogo = {"versione": numero, "variante": variante, "servizio": servizio, "fedelta_geometrica": fedelta,
                 "minuti_totali": round((time.time() - t0) / 60, 1),
                 "chiamate": len(registro.chiamate), "costo_openai_euro": round(registro.totale_euro("openai"), 2),
                 "costo_anthropic_euro": round(registro.totale_euro("anthropic"), 2),
                 "costo_totale_euro": round(registro.totale_euro(), 2), "tentativi": len(storia),
                 "modalita": scheda.get("modalita", "rinnova"), "metodo": "guidato"}
    (cartella / "riepilogo.json").write_text(json.dumps(riepilogo, indent=2, ensure_ascii=False), encoding="utf-8")
    return riepilogo
