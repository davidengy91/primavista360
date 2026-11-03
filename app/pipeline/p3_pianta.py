"""
STANZA DA PIANTINA (senza foto 360).

1) Claude legge la piantina (PDF o immagine) e restituisce la stanza scelta: misure, altezza, porte e finestre.
2) La stanza diventa la stessa "scatola" usata per le foto 360 (pareti, fissi, mobili a misura), con una
   fotocamera virtuale nel punto di ripresa: da lì si calcola la base 360 (il "modellino") per ChatGPT.

Convenzione della piantina (come la si guarda, in centimetri):
- larghezza = lato orizzontale, profondità = lato verticale;
- pareti: "alto" (= fondo, davanti alla fotocamera), "basso" (= dietro), "sinistra", "destra";
- "inizio" di un'apertura: da sinistra per le pareti alto/basso, dal basso per le pareti sinistra/destra;
- fotocamera: [x da sinistra, y dal basso], altezza 150 cm.
"""
import base64
from typing import Literal

from pydantic import BaseModel, Field

from ..servizi.api import blocco_immagine, chiedi_a_claude

PARETE = {"alto": "fondo", "basso": "dietro", "sinistra": "sinistra", "destra": "destra"}
ALTEZZA_CAMERA_CM = 150


class Apertura(BaseModel):
    tipo: Literal["porta", "finestra", "porta-finestra", "passaggio"]
    parete: Literal["alto", "basso", "sinistra", "destra"]
    inizio_cm: int = Field(description="distanza dall'angolo: da sinistra per pareti alto/basso, dal basso per sinistra/destra")
    larghezza_cm: int
    altezza_cm: int = Field(description="altezza del vano (porte ~210, finestre ~150, porte-finestre ~240)")
    davanzale_cm: int = Field(description="altezza da terra del bordo inferiore (0 per porte e porte-finestre)")


class StanzaLetta(BaseModel):
    trovata: bool = Field(description="false se nella piantina non c'è la stanza richiesta")
    nome: str
    larghezza_cm: int = Field(description="misura interna orizzontale come si guarda la piantina")
    profondita_cm: int = Field(description="misura interna verticale come si guarda la piantina")
    altezza_cm: int = Field(description="altezza del soffitto; se non è scritta 270")
    aperture: list[Apertura]
    note: str = Field(description="dubbi o approssimazioni (es. stanza a L approssimata a rettangolo, quota non leggibile)")


SISTEMA = """Sei un tecnico che legge piantine di appartamenti per un fotografo immobiliare.
Ricevi una piantina (disegno tecnico, catastale o schizzo) e il nome della stanza da rilevare.
Restituisci la stanza come RETTANGOLO interno, guardando la piantina così com'è (non ruotarla):
- usa le QUOTE scritte quando ci sono; se mancano, ricava le misure dalla scala o dalle proporzioni
  con porte standard da 80 cm, e scrivilo nelle note;
- pareti: alto, basso, sinistra, destra come appaiono nel disegno;
- per ogni porta, finestra, porta-finestra o passaggio aperto: parete, distanza dall'angolo
  (da sinistra per alto/basso, dal basso per sinistra/destra), larghezza, altezza e davanzale;
  valori tipici se non scritti: porte 80x210, finestre 120x150 con davanzale 90, porte-finestre 120x240;
- se la stanza non è rettangolare, approssimala al rettangolo principale e scrivilo nelle note.
Sii preciso: queste misure servono a costruire la stanza in scala."""


def leggi_pianta(dati_file, tipo_file, nome_stanza, ai, registro):
    """Claude legge la piantina. dati_file = bytes; tipo_file = 'pdf' oppure un'immagine (array BGR)."""
    if tipo_file == "pdf":
        allegato = {"type": "document", "source": {"type": "base64", "media_type": "application/pdf",
                                                   "data": base64.standard_b64encode(dati_file).decode()}}
    else:
        allegato = blocco_immagine(dati_file, 2000, 92)
    contenuto = [{"type": "text", "text": "Piantina:"}, allegato,
                 {"type": "text", "text": f"Stanza da rilevare: {nome_stanza or 'la stanza principale'}."}]
    registro.controlla(0.05, "lettura piantina")
    letta = chiedi_a_claude(contenuto, StanzaLetta, SISTEMA, ai["modello_claude"], registro,
                            "Lettura piantina (Claude)", sforzo="high")
    if not letta.trovata:
        raise RuntimeError(f"Nella piantina non ho trovato «{nome_stanza}». {letta.note}")
    return {"nome": letta.nome, "larghezza": letta.larghezza_cm, "profondita": letta.profondita_cm,
            "altezza": letta.altezza_cm, "camera": [round(letta.larghezza_cm / 2), round(letta.profondita_cm / 2)],
            "camera_h": ALTEZZA_CAMERA_CM, "note": letta.note,
            "aperture": [a.model_dump() for a in letta.aperture]}


def in_dati(pianta):
    """Dalla piantina (cm) ai dati della stanza usati da tutto il resto (metri, sistema della fotocamera)."""
    W, D = pianta["larghezza"] / 100, pianta["profondita"] / 100
    H = pianta.get("altezza", 270) / 100
    h = pianta.get("camera_h", ALTEZZA_CAMERA_CM) / 100
    cx, cz = pianta["camera"][0] / 100, pianta["camera"][1] / 100
    cx, cz = min(max(cx, 0.2), W - 0.2), min(max(cz, 0.2), D - 0.2)      # la fotocamera resta dentro la stanza
    fissi = []
    contatori = {}
    for a in pianta.get("aperture", []):
        parete = PARETE[a["parete"]]
        i0, i1 = a["inizio_cm"] / 100, (a["inizio_cm"] + a["larghezza_cm"]) / 100
        u = [i0 - cx, i1 - cx] if parete in ("fondo", "dietro") else [i0 - cz, i1 - cz]
        v0 = a.get("davanzale_cm", 0) / 100
        contatori[a["tipo"]] = contatori.get(a["tipo"], 0) + 1
        n = contatori[a["tipo"]]
        fissi.append({"tipo": a["tipo"], "nome": f"{a['tipo'].capitalize()}{' ' + str(n) if n > 1 else ''}",
                      "parete": parete, "u": u, "v": [v0, min(H, v0 + a["altezza_cm"] / 100)]})
    return {"altezza_camera": h, "inclinazione": {"pitch": 0, "roll": 0},
            "scatola": {"h": h, "theta": 0.0, "XL": -cx, "XR": W - cx, "ZB": -cz, "ZW": D - cz, "H": H},
            "fissi": fissi, "angoli": [], "spigoli": [], "pareti": {}, "soffitto": None}


# ------------------------------------------------------------------ CASA INTERA: tutte le stanze in una lettura

class StanzaCasa(BaseModel):
    nome: str = Field(description="nome del vano come scritto o come si capisce (es. 'Camera matrimoniale', 'Bagno', 'Cucina')")
    x0: int = Field(description="bordo sinistro della stanza sull'immagine, in millesimi della larghezza (0-1000)")
    y0: int = Field(description="bordo alto della stanza sull'immagine, in millesimi dell'altezza (0-1000)")
    x1: int = Field(description="bordo destro, millesimi della larghezza")
    y1: int = Field(description="bordo basso, millesimi dell'altezza")
    larghezza_cm: int
    profondita_cm: int
    altezza_cm: int = Field(description="se non è scritta 270")
    aperture: list[Apertura]
    note: str


class Casa(BaseModel):
    stanze: list[StanzaCasa]
    note: str = Field(description="dubbi generali: quote mancanti, scala stimata, parti illeggibili")


SISTEMA_CASA = """Sei un tecnico che legge piantine di appartamenti per un fotografo immobiliare.
Ricevi la piantina di una casa intera (griglia azzurra numerata in millesimi: 0-1000 in orizzontale e in verticale).
Elenca TUTTI i vani: camere, soggiorno, cucina, bagni, disimpegni, ripostigli, ingresso (non balconi e terrazzi).
Per ogni vano:
- il riquadro sull'immagine in millesimi (x0, y0, x1, y1), aderente ai muri interni del vano;
- le misure interne come RETTANGOLO, guardando la piantina così com'è (larghezza = orizzontale, profondità = verticale);
  usa le QUOTE scritte quando ci sono, altrimenti la scala o le proporzioni con porte standard da 80 cm (scrivilo nelle note);
- porte, finestre, porte-finestre e passaggi del vano: parete (alto, basso, sinistra, destra come nel disegno),
  distanza dall'angolo (da sinistra per alto/basso, dal basso per sinistra/destra), larghezza, altezza, davanzale;
  valori tipici se non scritti: porte 80x210, finestre 120x150 con davanzale 90, porte-finestre 120x240;
- se il vano non è rettangolare, il rettangolo principale e una nota.
Sii preciso: queste misure servono a costruire le stanze in scala."""


def _con_griglia_millesimi(img):
    import cv2
    h, w = img.shape[:2]
    scala = min(1.0, 2000 / max(h, w))
    out = cv2.resize(img, (int(w * scala), int(h * scala)), interpolation=cv2.INTER_AREA) if scala < 1 else img.copy()
    h, w = out.shape[:2]
    for i in range(1, 10):
        x, y = int(w * i / 10), int(h * i / 10)
        cv2.line(out, (x, 0), (x, h), (230, 180, 60), 1)
        cv2.line(out, (0, y), (w, y), (230, 180, 60), 1)
        cv2.putText(out, str(i * 100), (x + 3, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 140, 30), 1, cv2.LINE_AA)
        cv2.putText(out, str(i * 100), (3, y - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 140, 30), 1, cv2.LINE_AA)
    return out


def leggi_casa(dati_file, tipo_file, ai, registro):
    """Claude legge TUTTE le stanze della piantina. Restituisce l'elenco, ognuna nel formato di leggi_pianta
    più il riquadro sull'immagine (millesimi) per sceglierla con un clic."""
    if tipo_file == "pdf":
        allegato = {"type": "document", "source": {"type": "base64", "media_type": "application/pdf",
                                                   "data": base64.standard_b64encode(dati_file).decode()}}
    else:
        allegato = blocco_immagine(_con_griglia_millesimi(dati_file), 2000, 92)
    contenuto = [{"type": "text", "text": "Piantina della casa:"}, allegato,
                 {"type": "text", "text": "Elenca tutti i vani con riquadro, misure e aperture."}]
    registro.controlla(0.10, "lettura casa")
    casa = chiedi_a_claude(contenuto, Casa, SISTEMA_CASA, ai["modello_claude"], registro,
                           "Lettura piantina della casa (Claude)", sforzo="high")
    stanze = []
    for s in casa.stanze:
        stanze.append({"nome": s.nome, "riquadro": [s.x0, s.y0, s.x1, s.y1],
                       "larghezza": s.larghezza_cm, "profondita": s.profondita_cm, "altezza": s.altezza_cm,
                       "camera": [round(s.larghezza_cm / 2), round(s.profondita_cm / 2)], "camera_h": ALTEZZA_CAMERA_CM,
                       "note": s.note, "aperture": [a.model_dump() for a in s.aperture]})
    return stanze, casa.note
