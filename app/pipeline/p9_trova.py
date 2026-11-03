"""
TROVA LA ZONA dalla descrizione del cliente (niente ritagli a mano).

Il cliente scrive "sostituisci il letto con questo" e allega la foto del prodotto: Claude guarda il 360 e indica
il riquadro della zona da modificare (l'oggetto da sostituire per intero, oppure lo spazio dove aggiungere il prodotto).
Costo: una chiamata a Claude con una foto, circa 1 centesimo.
"""
import cv2
import numpy as np
from pydantic import BaseModel, Field

from ..servizi.api import blocco_immagine, chiedi_a_claude

LARGHEZZA = 2000          # la foto mandata a Claude è 2000 x 1000 px, con una griglia numerata per orientarsi
ALTEZZA = LARGHEZZA // 2

SISTEMA = """Sei l'assistente di un fotografo immobiliare. Ricevi una foto 360 equirettangolare di una stanza
(2000x1000 pixel, griglia numerata ogni 100 px) e la richiesta del cliente su un prodotto da provare nella stanza.
Devi indicare il RIQUADRO della zona da modificare, in pixel di quella foto:
- se il cliente vuole SOSTITUIRE un oggetto: il riquadro contiene l'oggetto vecchio INTERO (es. un letto con testiera,
  piedi e cuscini; un armadio con tutte le ante), con un piccolo margine;
- se vuole AGGIUNGERE un prodotto: il riquadro è lo spazio libero dove ha senso metterlo, grande quanto il prodotto.
La foto è un 360: un oggetto vicino alla fotocamera appare molto largo e curvo, includilo tutto.
Se l'oggetto attraversa il bordo sinistro/destro della foto, indica x0 maggiore di x1 (il riquadro passa dal bordo)."""


class Zona(BaseModel):
    trovato: bool = Field(description="false se nella foto non c'è nulla che corrisponda alla richiesta")
    cosa: str = Field(description="cosa hai individuato, in italiano, breve (es. 'il letto matrimoniale')")
    x0: int = Field(description="bordo sinistro del riquadro, pixel 0-2000")
    y0: int = Field(description="bordo alto del riquadro, pixel 0-1000")
    x1: int = Field(description="bordo destro del riquadro, pixel 0-2000")
    y1: int = Field(description="bordo basso del riquadro, pixel 0-1000")


def _con_griglia(equi):
    img = cv2.resize(equi, (LARGHEZZA, ALTEZZA), interpolation=cv2.INTER_AREA)
    for x in range(100, LARGHEZZA, 100):
        cv2.line(img, (x, 0), (x, ALTEZZA), (0, 255, 255), 1)
        cv2.putText(img, str(x), (x + 3, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1, cv2.LINE_AA)
    for y in range(100, ALTEZZA, 100):
        cv2.line(img, (0, y), (LARGHEZZA, y), (0, 255, 255), 1)
        cv2.putText(img, str(y), (3, y - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1, cv2.LINE_AA)
    return img


def maschera_riquadro(W, H, x0, y0, x1, y1):
    """Riquadro (pixel della foto 2000x1000) -> maschera del 360 W x H; gestisce il passaggio dal bordo 0/360."""
    m = np.zeros((H, W), np.uint8)
    a, b = int(x0 / LARGHEZZA * W), int(x1 / LARGHEZZA * W)
    r0, r1 = sorted((int(y0 / ALTEZZA * H), int(y1 / ALTEZZA * H)))
    if a <= b:
        m[r0:r1, a:b] = 1
    else:                                   # attraversa la giuntura
        m[r0:r1, a:] = 1
        m[r0:r1, :b] = 1
    return m > 0


def trova_zona(equi, istruzione, foto_prodotti, ai, registro):
    """Chiede a Claude dove va fatta la modifica. Restituisce (maschera del 360, descrizione) oppure (None, motivo)."""
    H, W = equi.shape[:2]
    contenuto = [{"type": "text", "text": "Foto 360 della stanza (2000x1000 px, griglia ogni 100 px):"},
                 blocco_immagine(_con_griglia(equi), LARGHEZZA)]
    for i, p in enumerate(foto_prodotti, 1):
        contenuto += [{"type": "text", "text": f"Foto del prodotto {i} da provare:"}, blocco_immagine(p, 512)]
    contenuto.append({"type": "text", "text": f"RICHIESTA DEL CLIENTE: {istruzione}\n\nIndica il riquadro della zona da modificare."})
    registro.controlla(0.03, "ricerca zona")
    z = chiedi_a_claude(contenuto, Zona, SISTEMA, ai["modello_claude"], registro, "Trova la zona (Claude)", sforzo="medium")
    if not z.trovato:
        return None, z.cosa
    x0, x1 = [int(np.clip(v, 0, LARGHEZZA)) for v in (z.x0, z.x1)]
    y0, y1 = [int(np.clip(v, 0, ALTEZZA)) for v in (z.y0, z.y1)]
    if abs(y1 - y0) < 10 or x0 == x1:
        return None, "riquadro troppo piccolo"
    return maschera_riquadro(W, H, x0, y0, x1, y1), z.cosa
