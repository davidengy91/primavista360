"""
Passo 3 - Analisi: Claude guarda tutte le viste originali e prepara il lavoro:
descrizione della stanza, elementi da non toccare, capitolato di stile unico,
da usare identico per tutta la ristrutturazione.
"""
from typing import List, Literal

from pydantic import BaseModel, Field

from ..servizi.api import blocco_immagine, chiedi_a_claude

SISTEMA = """Sei il direttore artistico di uno studio di fotografia immobiliare e home staging virtuale.
Ricevi le viste prospettiche estratte da una foto 360 di un ambiente reale e la richiesta del cliente.
Il tuo lavoro: preparare le istruzioni per un modello di generazione immagini che ristrutturerà
l'intero 360 in una sola immagine. Devi capire bene la stanza (guardando le viste) e scrivere
un capitolato preciso e un elenco completo degli elementi che non devono cambiare.

Regole:
- La struttura architettonica resta IDENTICA: muri, angoli, soffitto, finestre, porte, porta-finestra,
  radiatori se non richiesto diversamente, prospettiva e posizione della fotocamera.
- Pareti: lisce e tinteggiate. Mai boiserie a doghe, pannelli, nicchie, lesene o controsoffitti
  se il cliente non li chiede esplicitamente (deformano la percezione della struttura).
- Rispetta alla lettera i vincoli del cliente (es. elementi che devono restare nello stesso posto e misura).
- Il capitolato deve essere preciso e verificabile (materiale, finitura, colore, formato), non generico.
- Scrivi capitolato ed elementi fissi in INGLESE (il modello immagini li segue meglio); la descrizione in italiano.
- Gli elementi fissi devono essere localizzati (es. "entrance door and corridor on the left of the kitchen",
  "French door to the balcony"), così il modello li riconosce. Includi sempre corridoi, passaggi e porte.
- Arredo: completo, sensato, proporzionato alla stanza, nessun mobile davanti a porte o finestre.
- Luce: calda e naturale, 3500-4000K, coerente, con la luce del giorno dalle finestre reali.
- Niente persone, niente testo, niente loghi."""

MODALITA = {
    "rinnova": """MODALITÀ "RINNOVA": la disposizione dei mobili resta quella attuale.
Nel capitolato elenca OGNI mobile grande presente, con la sua posizione, e indica con cosa va sostituito:
un pezzo moderno equivalente con lo STESSO ingombro, la stessa posizione e la stessa sagoma
(es. "existing dining table in the centre, under the ceiling light -> same size rectangular table in ...").
Non aggiungere mobili grandi dove non ce ne sono e non toglierne. Togli solo il disordine e i piccoli oggetti
(tovaglie, soprammobili, quadri vecchi, oggetti personali), sostituendoli con pochi complementi eleganti.""",
    "potenziale": """MODALITÀ "POTENZIALE": puoi riprogettare la disposizione dell'arredo per mostrare il
potenziale della stanza, ma con mobili dalle forme semplici e regolari. Lascia libero il pavimento
nel raggio di circa 1 metro attorno alla fotocamera.""",
}


MAPPA = """MAPPA DELLA STANZA ("radar"): elenca TUTTI gli elementi importanti, ognuno con un id unico.
- categoria "fisso": architettura e impianti che devono restare IDENTICI (porte, porta d'ingresso, corridoi e
  passaggi, finestre, porta-finestra, condizionatore, radiatori, prese/interruttori, colonne, travi).
  Metti blocca_pixel=true SOLO per finestre e porte-finestre (la vista esterna viene rimessa con i pixel
  originali); per tutti gli altri elementi fissi blocca_pixel=false (restano protetti durante la generazione).
- categoria "rinnova": mobili e blocchi da modernizzare restando nello stesso posto e con lo stesso ingombro
  (cucina, tavolo, sedie, librerie, divani, letti, mobili bagno...).
- categoria "togli": disordine e oggetti da eliminare (tovaglie, soprammobili, quadri vecchi, oggetti personali,
  cavi, sedie spaiate), se nella richiesta non servono.
Per ogni elemento indica in quali viste compare e il riquadro che lo contiene in ciascuna vista, in coordinate
da 0 a 1000 (x1, y1 = angolo in alto a sinistra; x2, y2 = angolo in basso a destra; ogni vista è quadrata).
Riquadri STRETTI attorno all'oggetto, che lo contengono tutto ma senza muro o pavimento in più.
Un riquadro per OGNI oggetto fisico: se ci sono tre quadri, tre riquadri separati (anche nella stessa vista),
mai un unico riquadro grande che li racchiude tutti. Usa le viste orizzontali; zenit/nadir solo per oggetti
che si vedono solo lì (es. plafoniere)."""


RILIEVO = """RILIEVO GEOMETRICO (serve a calcolare le misure vere: la fotocamera è a 1,50 m da terra, livellata).
- angoli_pavimento: per OGNI angolo verticale della stanza (dove due pareti si incontrano), il punto esatto in cui
  lo spigolo tocca il PAVIMENTO, in una vista orizzontale dove si vede bene (coordinate 0-1000 della vista).
  Se il punto è nascosto da un mobile, stimalo prolungando la linea tra muro e pavimento. Includi anche gli angoli
  di rientranze e pilastri. Ogni angolo una sola volta.
- angoli_soffitto: per 2-4 angoli, il punto in cui lo spigolo verticale tocca il SOFFITTO (servono per l'altezza).
- Per ogni elemento "rinnova" appoggiato a terra (mobili, letto, tavolo, tappeto, cucina): in base_vista e base
  indica i due punti in cui lo SPIGOLO INFERIORE ANTERIORE (il lato verso la fotocamera) tocca il pavimento:
  base = [x_sinistra, y_sinistra, x_destra, y_destra] (0-1000). Stima profondita_cm e altezza_cm reali
  (tappeto: altezza 0). Per gli altri elementi lascia base_vista vuota, base [] e misure 0.
- pavimento_nuovo: come sarà posato il pavimento richiesto ("doghe" per parquet, "lastre" per grandi lastre,
  "piastrelle" per formati medi) e formato_cm [lunghezza, larghezza] del singolo pezzo."""


class Punto(BaseModel):
    vista: str
    x: int = Field(description="0-1000")
    y: int = Field(description="0-1000")


class Presenza(BaseModel):
    vista: str = Field(description="nome della vista, es. vista_03")
    riquadro: List[int] = Field(description="[x1, y1, x2, y2] da 0 a 1000")


class Elemento(BaseModel):
    id: str = Field(description="identificativo breve senza spazi, es. porta_ingresso")
    nome: str = Field(description="nome per il fotografo, italiano")
    categoria: Literal["fisso", "rinnova", "togli"]
    blocca_pixel: bool
    descrizione_en: str = Field(description="descrizione in inglese con posizione, per il modello immagini")
    presenze: List[Presenza]
    base_vista: str = Field(description="vista in cui si vede la base anteriore, oppure stringa vuota")
    base: List[int] = Field(description="[x_sx, y_sx, x_dx, y_dx] punti a terra dello spigolo anteriore, o []")
    profondita_cm: int
    altezza_cm: int


class Analisi(BaseModel):
    tipo_ambiente: str = Field(description="tipo di ambiente, breve, in italiano (es. 'Soggiorno con cucina a vista')")
    descrizione_stanza: str = Field(description="descrizione per il cliente, italiano")
    elementi_fissi: List[str] = Field(description="cosa non deve cambiare (aperture, corridoi, cucina...), "
                                                  "in inglese e con la posizione")
    capitolato_stile: str = Field(description="capitolato unico in inglese: materiali, colori, arredi, luce")
    elementi: List[Elemento] = Field(description="mappa della stanza (radar)")
    angoli_pavimento: List[Punto]
    angoli_soffitto: List[Punto]
    pavimento_nuovo: Literal["doghe", "lastre", "piastrelle"]
    formato_cm: List[int] = Field(description="[lunghezza, larghezza] del singolo pezzo di pavimento")


def analizza(viste_img, viste_param, richiesta, impostazioni_ai, registro, modalita="rinnova"):
    """viste_img: dict nome -> immagine; viste_param: lista dei parametri delle viste."""
    contenuto = []
    for v in viste_param:
        descr = (f"{v['nome']}: yaw {v['yaw']:.0f}°, pitch {v['pitch']:.0f}°, campo visivo {v['fov']}°"
                 + (" (soffitto)" if v["pitch"] > 45 else " (pavimento)" if v["pitch"] < -45 else ""))
        contenuto.append({"type": "text", "text": descr})
        contenuto.append(blocco_immagine(viste_img[v["nome"]], impostazioni_ai["lato_viste_per_claude"]))
    contenuto.append({"type": "text", "text":
                      "Le viste orizzontali sono ogni 45° e si sovrappongono: vista_01 confina con vista_02 a destra "
                      "e con vista_08 a sinistra.\n\n" + MODALITA.get(modalita, MODALITA["rinnova"]) +
                      "\n\n" + MAPPA + "\n\n" + RILIEVO +
                      "\n\nRICHIESTA DEL CLIENTE:\n" + richiesta + "\n\nPrepara l'analisi completa."})
    return chiedi_a_claude(contenuto, Analisi, SISTEMA, impostazioni_ai["modello_claude"],
                           registro, "Analisi stanza (Claude)")
