"""
Passo 6 - Controllo qualità: Claude confronta il 360 originale con quello ristrutturato,
guardando anche viste prospettiche estratte nei punti critici (giuntura del 360, pavimento,
soffitto, le quattro direzioni) e segnala i problemi.
Se il risultato non è consegnabile, scrive istruzioni aggiuntive per rifarlo meglio.
"""
from typing import List, Literal

from pydantic import BaseModel, Field

from ..servizi.api import blocco_immagine, chiedi_a_claude
from .geometria import estrai_vista

SISTEMA = """Sei il controllo qualità di uno studio di home staging virtuale 360.
Confronti la foto 360 originale con la versione ristrutturata e decidi se è consegnabile a un cliente.
Cerca difetti che un cliente noterebbe in un tour virtuale:
- architettura cambiata: muri, angoli, finestre, porte, porta-finestra, corridoi, passaggi spostati,
  aggiunti, eliminati o di forma diversa (è il difetto più grave: la stanza deve restare identica);
- vincoli del cliente non rispettati (es. cucina spostata o di misura diversa);
- mobili tagliati, doppi, fusi, fluttuanti o senza senso; tappeti interrotti;
- DISTORSIONI: nelle viste prospettiche (non nel 360 piatto, dove le curve sono normali) i bordi di
  tappeti, tavoli, divani, mobili e fughe del pavimento devono essere DRITTI e regolari. Un tappeto ondulato,
  piegato o deformato, o un mobile storto, è un difetto grave (voto massimo 6);
- giunture visibili (soprattutto nella vista "giuntura", dove il bordo destro del 360 si unisce al sinistro);
- pavimento sotto la fotocamera sporco, con il treppiede o con linee che convergono in modo strano;
- luce incoerente, persone, testo, artefatti.
Il voto va da 1 a 10: 8 o più = consegnabile. Sii severo ma concreto."""


class Problema(BaseModel):
    dove: str
    descrizione: str = Field(description="italiano")
    gravita: Literal["bassa", "media", "alta"]


class EsitoControllo(BaseModel):
    voto: int = Field(description="qualità complessiva da 1 a 10")
    giudizio: str = Field(description="sintesi per il fotografo, italiano")
    problemi: List[Problema]
    rifare: bool = Field(description="true se il risultato non è consegnabile e va rigenerato")
    istruzioni_extra: str = Field(description="se rifare=true: istruzioni in inglese da aggiungere al prompt "
                                              "per evitare i difetti trovati; altrimenti stringa vuota")


def viste_di_controllo(equi, lato=768):
    """Le viste che Claude guarda per il controllo (etichetta, immagine)."""
    viste = [("giuntura del 360 (bordo destro + sinistro)", estrai_vista(equi, 180, 0, 100, lato))]
    for yaw, nome in ((0, "fronte"), (90, "destra"), (270, "sinistra")):
        viste.append((f"direzione {nome} (yaw {yaw}°)", estrai_vista(equi, yaw, -10, 100, lato)))
    # viste in diagonale verso il pavimento: qui si vede se tappeti e mobili sono storti
    for yaw in (45, 135, 225, 315):
        viste.append((f"pavimento in diagonale (yaw {yaw}°, guardando in basso)", estrai_vista(equi, yaw, -45, 90, lato)))
    viste.append(("pavimento sotto la fotocamera (nadir)", estrai_vista(equi, 0, -90, 110, lato)))
    viste.append(("soffitto (zenit)", estrai_vista(equi, 0, 90, 110, lato)))
    return viste


ATTESE_MODALITA = {
    "rinnova": "Modalità RINNOVA: ogni mobile grande deve restare nella stessa posizione e con lo stesso ingombro "
               "dell'originale (solo modernizzato). Mobili spostati, aggiunti o tolti sono un difetto.",
    "potenziale": "Modalità POTENZIALE: l'arredo può essere riprogettato, ma deve essere sensato e senza "
                  "mobili sotto la fotocamera.",
}


def _elenco_mappa(elementi):
    nomi = {"fisso": "FISSO (identico)", "rinnova": "RINNOVA (stesso posto e ingombro)", "togli": "TOGLI"}
    return "\n".join(f"- {nomi.get(e['categoria'], e['categoria'])}: {e['nome']} ({e['descrizione_en']})"
                     for e in (elementi or [])) or "- (nessuna)"


def controlla(originale_equi, risultato_equi, richiesta, analisi, punteggio_struttura, ai, registro,
              modalita="rinnova", elementi=None):
    lato = ai["lato_viste_per_claude"]
    contenuto = [
        {"type": "text", "text": "FOTO 360 ORIGINALE:"}, blocco_immagine(originale_equi, 1600),
        {"type": "text", "text": "360 RISTRUTTURATO:"}, blocco_immagine(risultato_equi, 1600),
    ]
    for (etichetta, vista_r), (_, vista_o) in zip(viste_di_controllo(risultato_equi, lato),
                                                  viste_di_controllo(originale_equi, lato)):
        contenuto += [{"type": "text", "text": f"{etichetta} - ORIGINALE:"}, blocco_immagine(vista_o, lato),
                      {"type": "text", "text": f"{etichetta} - RISTRUTTURATO:"}, blocco_immagine(vista_r, lato)]
    contenuto.append({"type": "text", "text":
                      f"{ATTESE_MODALITA.get(modalita, '')}\n"
                      f"Mappa confermata dal fotografo (controlla OGNI elemento):\n{_elenco_mappa(elementi)}\n"
                      f"Richiesta del cliente: {richiesta}\n"
                      f"Elementi fissi: {'; '.join(analisi.elementi_fissi)}\n"
                      f"Capitolato: {analisi.capitolato_stile}\n"
                      f"Controllo geometrico automatico: {punteggio_struttura:.0f}/100 delle linee strutturali "
                      f"dell'originale sono ancora al loro posto (le linee dei vecchi mobili è normale che cambino; "
                      f"sotto 55 di solito l'architettura è stata alterata).\n\nValuta il risultato."})
    return chiedi_a_claude(contenuto, EsitoControllo, SISTEMA, ai["modello_claude"], registro,
                           "Controllo qualità (Claude)")
