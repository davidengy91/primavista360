"""
Proposta d'arredo a misura (servizio Progetta).

Claude riceve la stanza ricostruita in metri (pareti, porte, finestre, termosifoni), la richiesta del cliente
e una vista della foto, e propone dove mettere ogni mobile e con quali misure, seguendo le regole
di un progettista d'interni. Il programma poi VERIFICA la proposta (sovrapposizioni, mobili fuori dalla
stanza, porte bloccate, troppo vicino alla fotocamera) e, se serve, la fa correggere una volta.

Sistema di riferimento (lo stesso del rilievo): x = sinistra/destra, z = dietro/avanti, metri, camera in (0, 0).
Pareti: A = fondo (z = ZW), B = destra (x = XR), C = dietro (z = ZB), D = sinistra (x = XL).
"""
import math
from typing import List, Literal

import cv2
import numpy as np
from pydantic import BaseModel, Field

from ..servizi.api import blocco_immagine, chiedi_a_claude
from .p3_stanza import PRESET_MOBILI, angoli_mobile, costruisci

LETTERE = {"fondo": "A", "destra": "B", "dietro": "C", "sinistra": "D"}

SISTEMA = """Sei un architetto d'interni esperto di home staging per agenzie immobiliari.
Progetti la disposizione dei mobili di una stanza reale di cui conosci le misure esatte in metri.
La proposta deve essere realistica, proporzionata alla stanza e vendibile: meglio pochi mobili ben messi
che una stanza affollata.

REGOLE DI PROGETTO (rispettale tutte):
- Usa misure reali di mercato: letto matrimoniale 160×200, singolo 90×200, comodino 45×40, armadio prof. 60
  (con 70 cm liberi davanti per aprirlo), cassettiera prof. 50, divano 3 posti 210-240 × 90-95, poltrona 80×85,
  tavolino basso, tavolo da pranzo 4 posti 140×80 (6 posti 180×90), sedie 45×50, basi cucina prof. 60 h 90,
  pensili prof. 35, mobile TV prof. 40, scrivania 120×60, libreria prof. 35, tappeti 160×230 o 200×300.
- Passaggi liberi di almeno 70-80 cm. Letto: almeno un lato lungo libero di 60 cm (meglio entrambi nei
  matrimoniali) e 30-50 cm ai piedi. Se la stanza non lo permette, scegli un letto più piccolo
  (matrimoniale 160 -> francese 140 -> una piazza e mezza 120 -> singolo 90) invece di forzarlo.
- Occupa al massimo il 40% del pavimento: una stanza piccola va arredata con pochi pezzi essenziali.
- Davanti a ogni porta una zona libera di 90 cm; non coprire finestre e porte-finestre con mobili alti
  (sotto una finestra solo mobili bassi, sotto i 90 cm); lascia 20 cm davanti ai termosifoni.
- I mobili contenitori, il letto (testiera), il divano e la cucina vanno appoggiati a una parete piena.
- Composizione ordinata e simmetrica sull'asse principale, zone logiche (notte, giorno, pranzo, cucina).
- Mobili alti più di 50 cm il più lontano possibile dalla fotocamera (punto 0,0): almeno 1,3 m, o nelle stanze
  piccole almeno il 18% del lato corto della stanza, altrimenti in foto sembrerebbero enormi.
  Un tappeto può passare vicino alla fotocamera.
- Tutti i mobili dentro la stanza, senza sovrapporsi tra loro (il tappeto può stare sotto letto, divano, tavolo).

BAGNI (se la stanza è un bagno):
- Un bagno ha SEMPRE i sanitari: wc sospeso 36×55 h 40, lavabo con mobile 60-100 × 45-50 h 85, doccia
  80×80 / 70×120 / 90×120 h 200 (box in vetro) oppure vasca 170×70 h 55 se c'è spazio; bidet 36×55 h 40 solo se ci sta.
- Sanitari e doccia contro le pareti, possibilmente dove erano prima (gli attacchi di acqua e scarico sono lì:
  guarda la foto PRIMA dello svuotamento, se c'è). Davanti a wc e bidet 55-60 cm liberi, davanti al lavabo 70 cm.
- Nei bagni la regola della distanza dalla fotocamera NON vale per sanitari, lavabo e doccia: in un bagno piccolo
  stanno per forza vicini. Tappeto e portasciugamani sono accessori facoltativi, non sostituiscono i sanitari.

CUCINE (se la stanza è una cucina):
- Basi prof. 60 h 90 lungo le pareti (lineare, a L o a U), pensili prof. 35 sopra le basi, colonna frigo 60×60 h 215;
  piano cottura e lavello con almeno 60 cm di piano accanto; tavolo solo se resta un passaggio di 90 cm.

COME SCRIVERE LA PROPOSTA:
- centro_x_m, centro_z_m = centro del mobile visto dall'alto, nel sistema della stanza.
- rotazione = verso quale parete è rivolto il RETRO del mobile (lo schienale del divano, la testiera del letto):
  0 = retro verso la parete A, 90 = verso la parete B, 180 = verso la parete C, 270 = verso la parete D.
  Con rotazione 0 o 180 la larghezza corre lungo x; con 90 o 270 corre lungo z.
- Un mobile appoggiato alla parete A ha centro_z_m = ZW - profondità/2 (e così per le altre pareti).
- Scrivi il ragionamento in italiano, breve."""


class MobileProposto(BaseModel):
    nome: str = Field(description="nome breve in italiano, es. 'Letto matrimoniale', 'Comodino sinistro'")
    tipo: str = Field(description="tipo di mobile, es. letto, comodino, armadio, divano, tavolo, cucina, tappeto")
    larghezza_cm: int
    profondita_cm: int
    altezza_cm: int
    forma: Literal["box", "cilindro"]
    centro_x_m: float
    centro_z_m: float
    rotazione: int = Field(description="0, 90, 180 o 270")


class Proposta(BaseModel):
    ragionamento: str
    mobili: List[MobileProposto]


def descrivi_stanza(s):
    """La stanza in parole e numeri, per Claude."""
    L, P = s["XR"] - s["XL"], s["ZW"] - s["ZB"]
    righe = [
        f"Stanza rettangolare {L:.2f} m (lungo x) × {P:.2f} m (lungo z), altezza {s['H']:.2f} m.",
        f"Pareti: A (fondo) a z = {s['ZW']:.2f}; B (destra) a x = {s['XR']:.2f}; "
        f"C (dietro) a z = {s['ZB']:.2f}; D (sinistra) a x = {s['XL']:.2f}.",
        f"Pavimento da x {s['XL']:.2f} a {s['XR']:.2f}, da z {s['ZB']:.2f} a {s['ZW']:.2f}. Fotocamera in (0, 0), "
        f"alta {s['h']:.2f} m.",
        "Elementi fissi (posizione lungo la parete: per A e C è la x, per B e D è la z; altezza da terra):",
    ]
    for f in s["fissi"]:
        righe.append(f"- {f['tipo']} «{f['nome']}» sulla parete {LETTERE[f['parete']]}: da {f['u'][0]:.2f} a "
                     f"{f['u'][1]:.2f} m, altezza da {f['v'][0]:.2f} a {f['v'][1]:.2f} m")
    if not s["fissi"]:
        righe.append("- nessuno segnato (chiedi comunque di lasciare libere le zone delle porte visibili in foto)")
    return "\n".join(righe)


def verifica(s):
    """Problemi della proposta: avvisi del rilievo + mobili che si sovrappongono."""
    # nelle stanze piccole la regola "1,3 m dalla fotocamera" è impossibile: si proporziona alla stanza
    lato_min = min(s["XR"] - s["XL"], s["ZW"] - s["ZB"])
    vicino = min(1.3, max(0.3, 0.18 * lato_min))
    problemi = [a for a in s.get("avvisi", []) if "fotocamera" not in a]
    for m in s["mobili"]:
        if m["A"] < 0.5:
            continue
        testo = f"{m.get('nome', '')} {m.get('tipo', '')}".lower()
        if any(p in testo for p in ("wc", "bidet", "lavabo", "doccia", "vasca", "sanitar", "bagno")):
            continue            # nei bagni sanitari e doccia stanno per forza vicini alla fotocamera
        if m.get("forma") == "cilindro":
            d = math.hypot(*m["centro_m"]) - m["L"] / 2
        else:
            pts = angoli_mobile(m)
            d = min(math.hypot(*p) for p in pts)
            d = min(d, min(_dist_segmento(pts[i], pts[(i + 1) % 4]) for i in range(4)))
        if d < vicino:
            problemi.append(f"{m.get('nome')}: è a {d:.2f} m dalla fotocamera (minimo {vicino:.2f} m in questa stanza): "
                            "in foto sembrerebbe enorme, spostalo verso la parete.")
    poligoni = []
    for m in s["mobili"]:
        if m.get("forma") == "cilindro":
            r = m["L"] / 2
            c = np.array(m["centro_m"])
            pts = [c + r * np.array([math.cos(a), math.sin(a)]) for a in np.linspace(0, 2 * math.pi, 12, endpoint=False)]
        else:
            pts = angoli_mobile(m)
        poligoni.append((m, np.float32(pts)))
    # spazi d'uso: davanti a letti, armadi, divani, cucine deve restare un passaggio vero
    stanza_x, stanza_z = (s["XL"], s["XR"]), (s["ZB"], s["ZW"])
    area_mobili = 0.0
    for m, pts in poligoni:
        if m["A"] < 0.05:
            continue
        area_mobili += m["L"] * m["P"]
        nome = (m.get("tipo") or m.get("nome", "")).lower()
        if m.get("forma") == "cilindro":
            continue
        a = math.radians(m["rot"])
        davanti = -np.array([math.sin(a), math.cos(a)])          # il fronte è opposto al retro
        lato = np.array([math.cos(a), -math.sin(a)])
        c = np.array(m["centro_m"])

        def spazio(direzione, mezzo):
            """Distanza libera dal bordo del mobile alla parete in quella direzione."""
            bordo = c + direzione * mezzo
            dist = []
            for k, (lo, hi) in enumerate((stanza_x, stanza_z)):
                if direzione[k] > 0.3:
                    dist.append((hi - bordo[k]) / direzione[k])
                elif direzione[k] < -0.3:
                    dist.append((lo - bordo[k]) / direzione[k])
            return min(dist) if dist else 9.0

        if "letto" in nome:
            piedi = spazio(davanti, m["P"] / 2)
            fianchi = max(spazio(lato, m["L"] / 2), spazio(-lato, m["L"] / 2))
            if piedi < 0.3 or fianchi < 0.6:
                problemi.append(f"{m.get('nome')}: serve almeno un lato libero di 60 cm e 30 cm ai piedi "
                                f"(ai piedi {max(piedi, 0):.2f} m, lato più libero {max(fianchi, 0):.2f} m): "
                                f"usa un letto più piccolo (es. singolo 90×200 o 120×200) o spostalo.")
        elif any(p in nome for p in ("armadio", "cucina", "basi", "divano", "comò", "cassettiera", "libreria")):
            if spazio(davanti, m["P"] / 2) < (0.7 if "armadio" in nome or "cucina" in nome or "basi" in nome else 0.6):
                problemi.append(f"{m.get('nome')}: davanti non resta spazio sufficiente per usarlo/aprirlo.")
    superficie = (s["XR"] - s["XL"]) * (s["ZW"] - s["ZB"])
    if superficie > 0 and area_mobili / superficie > 0.45:
        problemi.append(f"I mobili occupano il {100 * area_mobili / superficie:.0f}% del pavimento: troppo pieno, "
                        "togli qualcosa o usa misure più piccole (massimo circa 40%).")
    for i in range(len(poligoni)):
        for j in range(i + 1, len(poligoni)):
            (a, pa), (b, pb) = poligoni[i], poligoni[j]
            if min(a["A"], b["A"]) < 0.05:          # il tappeto può stare sotto gli altri mobili
                continue
            area, _ = cv2.intersectConvexConvex(pa, pb)
            if area > 0.02:
                problemi.append(f"{a.get('nome')} e {b.get('nome')} si sovrappongono ({area:.2f} m²).")
    return problemi


def _dist_segmento(a, b):
    """Distanza della fotocamera (0, 0) dal segmento a-b."""
    ab = b - a
    t = float(np.clip(np.dot(-a, ab) / max(np.dot(ab, ab), 1e-9), 0, 1))
    return float(np.linalg.norm(a + t * ab))


def in_mobili(proposta):
    """Dalla proposta di Claude al formato dei mobili del rilievo."""
    mobili = []
    for p in proposta.mobili:
        preset = next((k for k in PRESET_MOBILI if p.tipo.lower() in k.lower()), None)
        mobili.append({"nome": p.nome, "tipo": preset or p.nome, "larghezza": int(p.larghezza_cm),
                       "profondita": int(p.profondita_cm), "altezza": int(p.altezza_cm), "forma": p.forma,
                       "muro": False, "centro": [round(p.centro_x_m, 3), round(p.centro_z_m, 3)],
                       "rotazione": int(round(p.rotazione / 90) * 90) % 360, "quota": 0, "proposto": True})
    return mobili


def proponi(dati, foto_equi, richiesta, ai, registro, servizio="arreda", foto_prima=None):
    """Chiede a Claude una disposizione a misura, la verifica e se serve la fa correggere (max 2 chiamate).
    Restituisce (mobili, ragionamento, problemi_rimasti)."""
    s = costruisci({**dati, "mobili": []})
    if "errore" in s:
        raise RuntimeError(f"Rilievo non valido: {s['errore']}")
    contenuto = [{"type": "text", "text": "Foto 360 della stanza (equirettangolare, la fotocamera è al centro):"},
                 blocco_immagine(foto_equi, 1600)]
    if foto_prima is not None:
        # stanza svuotata: la foto di prima mostra dov'erano sanitari, cucina e attacchi
        contenuto += [{"type": "text", "text": "La stessa stanza PRIMA dello svuotamento (com'era arredata):"},
                      blocco_immagine(foto_prima, 1600)]
    contenuto += [
                 {"type": "text", "text":
                  ("La stanza è VUOTA: progetta l'arredo da zero.\n" if servizio == "arreda" else
                   "La stanza va riprogettata: ignora i mobili attuali e progetta una disposizione nuova.\n") +
                  descrivi_stanza(s) + f"\n\nRICHIESTA DEL CLIENTE:\n{richiesta}\n\nProponi la disposizione."}]
    proposta = chiedi_a_claude(contenuto, Proposta, SISTEMA, ai["modello_claude"], registro,
                               "Proposta arredo (Claude)")
    mobili = in_mobili(proposta)
    problemi = verifica(costruisci({**dati, "mobili": mobili}))
    if problemi:
        contenuto.append({"type": "text", "text":
                          "La tua proposta era:\n" + proposta.model_dump_json() +
                          "\n\nIl controllo automatico ha trovato questi problemi, correggili tutti:\n- " +
                          "\n- ".join(problemi)})
        proposta = chiedi_a_claude(contenuto, Proposta, SISTEMA, ai["modello_claude"], registro,
                                   "Correzione proposta arredo (Claude)")
        mobili = in_mobili(proposta)
        problemi = verifica(costruisci({**dati, "mobili": mobili}))
    return mobili, proposta.ragionamento, problemi
