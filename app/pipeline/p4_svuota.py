"""
SVUOTA STANZA: da un 360 arredato a un 360 della stessa stanza vuota (ChatGPT, circa 0,10-0,25 €).

La stanza vuota diventa la nuova base del progetto: il rilievo automatico misura meglio (niente mobili
che nascondono gli angoli) e il cliente può poi scegliere dove mettere le cose (Arreda / Riprogetta).
La foto arredata originale resta salvata accanto (originale_ridotto_arredata.jpg).
"""
import json
import logging
import os
from pathlib import Path
from types import SimpleNamespace

import cv2

from ..servizi.api import modifica_immagine
from ..servizi.costi import BudgetSuperato, RegistroCosti
from .p4_equirect import correggi_giuntura
from .p4_guidata import RADICE, giunzione_ok

log = logging.getLogger(__name__)
LARGHEZZA = 3840

PROMPT_SVUOTA = """Ti allego un 360 equirettangolare di una stanza reale arredata.
SVUOTA la stanza: togli TUTTI i mobili, i tappeti, gli oggetti, i quadri, le tende e i soprammobili.
Resta solo la stanza vuota e pulita, com'è dopo un trasloco.

Restano IDENTICI e al loro posto: pareti, angoli, soffitto, pavimento (stesso materiale e disegno, completato
dove c'erano i mobili), porte, finestre e porte-finestre con i loro infissi, termosifoni, condizionatori,
prese, interruttori, punti luce, travi e gradini.
Dove c'erano i mobili ricostruisci in modo realistico la parete e il pavimento che stavano dietro, con la stessa
luce e le stesse ombre della stanza. Niente macchie, niente aloni, niente sagome dei mobili tolti.

Stesso punto di vista, stessa inquadratura, stessa luce. 360 equirettangolare 2:1 con i bordi destro e sinistro
che combaciano. Fotorealistico, nessun testo."""


def svuota(cartella, avanzamento=None):
    """Svuota il 360 del progetto e lo mette come nuova base. Restituisce il 360 vuoto (4096 x 2048)."""
    cartella = Path(cartella)
    ai = json.loads((RADICE / "config" / "impostazioni.json").read_text(encoding="utf-8"))["ai"]
    registro = RegistroCosti(cartella / "costi.json", os.getenv("SPESA_MASSIMA_EURO", "5"))
    if (cartella / "costi.json").exists():
        registro.chiamate = json.loads((cartella / "costi.json").read_text(encoding="utf-8")).get("chiamate", [])

    def fase(testo):
        log.info(">> %s", testo)
        if avanzamento:
            avanzamento("svuota", testo)

    # si parte sempre dalla foto ARREDATA originale (anche se si rifà lo svuotamento)
    arredata = cartella / "originale_ridotto_arredata.jpg"
    if not arredata.exists():
        cv2.imwrite(str(arredata), cv2.imread(str(cartella / "originale_ridotto.jpg")), [cv2.IMWRITE_JPEG_QUALITY, 95])
    foto = cv2.resize(cv2.imread(str(arredata)), (LARGHEZZA, LARGHEZZA // 2), interpolation=cv2.INTER_AREA)

    fase("ChatGPT svuota la stanza (circa 1 minuto)")
    registro.controlla(0.15, "svuota stanza")
    out = modifica_immagine([foto], PROMPT_SVUOTA, None, ai["modello_immagini"], None, ai.get("qualita_360", "high"),
                            registro, "Svuota stanza", dimensione=f"{LARGHEZZA}x{LARGHEZZA // 2}")
    out = cv2.resize(out, (LARGHEZZA, LARGHEZZA // 2), interpolation=cv2.INTER_LANCZOS4)
    cv2.imwrite(str(cartella / "svuotata_grezza.png"), out)

    fase("Controllo della giunzione 0°/360°")
    ok, _ = giunzione_ok(out)
    if not ok:
        try:
            registro.controlla(0.12, "giunzione")
            out = correggi_giuntura(out, SimpleNamespace(capitolato_stile="stanza vuota, pareti e pavimento originali",
                                                         elementi_fissi=["porte", "finestre"]), ai, registro, cartella)
        except BudgetSuperato as e:
            log.warning(str(e))

    fase("La stanza vuota diventa la base del progetto")
    vuota = cv2.resize(out, (4096, 2048), interpolation=cv2.INTER_CUBIC)
    cv2.imwrite(str(cartella / "originale_ridotto.jpg"), vuota, [cv2.IMWRITE_JPEG_QUALITY, 92])
    cv2.imwrite(str(cartella / "viewer_prima.jpg"), vuota, [cv2.IMWRITE_JPEG_QUALITY, 90])
    cv2.imwrite(str(cartella / "miniatura.jpg"), cv2.resize(vuota, (800, 400), interpolation=cv2.INTER_AREA),
                [cv2.IMWRITE_JPEG_QUALITY, 85])
    return vuota
