"""
Esegue tutta la procedura su un 360, in due fasi.

FASE A - prepara()  (circa 1 minuto)
  1. controllo della foto
  2. taglio in viste (servono a Claude per capire bene la stanza)
  3. analisi di Claude: stanza, capitolato di stile e MAPPA ("radar") di ogni elemento:
     fisso / da rinnovare / da togliere, con la sua posizione sul 360
  -> il fotografo guarda la mappa, corregge se serve e conferma

FASE B - genera()
  4. ristrutturazione del 360 intero in una sola immagine (OpenAI), guidata da mappa e disegno a linee
  5. correzione della giuntura del 360 e del pavimento sotto il treppiede
  6. blocco degli elementi fissi: tornano i pixel originali (identici per costruzione)
  7. controllo geometrico (gratis) + controllo qualità di Claude; se serve si rifà (max "tentativi")
  8. JPG 360 alla risoluzione originale con metadati 360

Uso da riga di comando (conferma automatica della mappa):
    python -m app.pipeline.esegui foto360.jpg "cosa voglio ottenere"
"""
import json
import logging
import os
import re
import sys
import time
from pathlib import Path

import cv2
import numpy as np

from ..servizi.costi import BudgetSuperato, RegistroCosti
from .geometria import estrai_vista
from .p2_taglio import schema_viste
from .p3_analisi import Analisi, analizza
from .p3_mappa import blocca_elementi_fissi, calcola_maschere, disegno_linee, immagine_mappa, maschera_protetta
from .p4_equirect import correggi_giuntura, correggi_polo, genera_360
from .p6_controllo import controlla
from .p6_geometria import punteggio_struttura
from .p7_output import salva_jpg_360

RADICE = Path(__file__).resolve().parents[2]
log = logging.getLogger("primavista")

# fasi mostrate nell'interfaccia (chiave -> nome)
FASI = {
    "controllo_foto": "Controllo foto",
    "taglio": "Taglio in viste",
    "analisi": "Analisi e mappa della stanza",
    "conferma": "Tua conferma della mappa",
    "ristrutturazione": "Ristrutturazione 360",
    "correzioni": "Giunture, pavimento, elementi fissi",
    "qualita": "Controllo qualità",
    "consegna": "Preparazione consegna",
}


def carica_impostazioni():
    return json.loads((RADICE / "config" / "impostazioni.json").read_text(encoding="utf-8"))


def nome_cartella(richiesta):
    breve = re.sub(r"[^a-z0-9]+", "_", richiesta.lower())[:40].strip("_") or "progetto"
    return time.strftime("%Y%m%d_%H%M%S_") + breve


def _configura_log(cartella):
    log.setLevel(logging.INFO)
    for h in list(log.handlers):
        log.removeHandler(h)
    formato = logging.Formatter("%(asctime)s  %(levelname)-7s  %(message)s", "%H:%M:%S")
    for h in (logging.FileHandler(cartella / "log.txt", encoding="utf-8"), logging.StreamHandler(sys.stdout)):
        h.setFormatter(formato)
        log.addHandler(h)


def _registro(cartella):
    registro = RegistroCosti(cartella / "costi.json", os.getenv("SPESA_MASSIMA_EURO", "5"))
    precedenti = json.loads((cartella / "costi.json").read_text(encoding="utf-8")) if (cartella / "costi.json").exists() else {}
    registro.chiamate = precedenti.get("chiamate", [])   # la fase B continua il conto della fase A
    return registro


def _fase(avanzamento):
    def fase(chiave, testo):
        log.info(">> %s", testo)
        if avanzamento:
            avanzamento(chiave, testo)
    return fase


def verifica_input(equi):
    """Controlla che sia un 360 equirettangolare 2:1."""
    h, w = equi.shape[:2]
    if abs(w / h - 2) > 0.01:
        raise ValueError(f"L'immagine è {w}x{h}: non è un 360 equirettangolare (serve rapporto 2:1).")
    if w < 4000:
        log.warning("Risoluzione bassa (%d px): il risultato sarà poco nitido.", w)


# ------------------------------------------------------------------ FASE A

def prepara(percorso_360, richiesta, cartella, modalita="rinnova", avanzamento=None):
    """Taglio + analisi + mappa. Salva tutto nella cartella del progetto."""
    impostazioni = carica_impostazioni()
    ai = impostazioni["ai"]
    cartella = Path(cartella)
    cartella.mkdir(parents=True, exist_ok=True)
    _configura_log(cartella)
    fase = _fase(avanzamento)
    registro = _registro(cartella)
    t0 = time.time()

    scheda = {}
    if (cartella / "richiesta.json").exists():   # creata dall'interfaccia web (contiene il nome del file)
        scheda = json.loads((cartella / "richiesta.json").read_text(encoding="utf-8"))
    scheda.update({"foto": str(percorso_360), "richiesta": richiesta, "modalita": modalita,
                   "data": scheda.get("data") or time.strftime("%d/%m/%Y %H:%M"), "impostazioni": impostazioni})
    (cartella / "richiesta.json").write_text(json.dumps(scheda, indent=2, ensure_ascii=False), encoding="utf-8")

    fase("controllo_foto", "Controllo foto 360")
    originale = cv2.imread(str(percorso_360), cv2.IMREAD_COLOR)
    if originale is None:
        raise FileNotFoundError(percorso_360)
    verifica_input(originale)
    equi_lavoro = cv2.resize(originale, (4096, 2048), interpolation=cv2.INTER_AREA)
    cv2.imwrite(str(cartella / "originale_ridotto.jpg"), equi_lavoro, [cv2.IMWRITE_JPEG_QUALITY, 92])

    fase("taglio", "Taglio in viste")
    lato = ai["lato_vista_ai"]
    viste_param = schema_viste(4096, **impostazioni["taglio"], lato_fisso=lato)
    (cartella / "viste.json").write_text(json.dumps(viste_param, indent=2), encoding="utf-8")
    cart_viste = cartella / "viste_originali"
    cart_viste.mkdir(exist_ok=True)
    originali = {}
    for v in viste_param:
        originali[v["nome"]] = estrai_vista(equi_lavoro, v["yaw"], v["pitch"], v["fov"], lato, lato)
        cv2.imwrite(str(cart_viste / f"{v['nome']}.jpg"), originali[v["nome"]])

    fase("analisi", "Claude studia la stanza e prepara la mappa")
    registro.controlla(0.4, "analisi")
    analisi = analizza(originali, viste_param, richiesta, ai, registro, modalita)
    (cartella / "analisi.json").write_text(analisi.model_dump_json(indent=2), encoding="utf-8")
    log.info("Stanza: %s - %d elementi in mappa", analisi.tipo_ambiente, len(analisi.elementi))

    disegna_mappa(cartella)
    (cartella / "tempi.json").write_text(json.dumps({"prepara": round(time.time() - t0)}), encoding="utf-8")
    return analisi


def disegna_mappa(cartella, elementi=None):
    """(Ri)disegna l'immagine della mappa; usa le categorie confermate se ci sono."""
    cartella = Path(cartella)
    analisi = json.loads((cartella / "analisi.json").read_text(encoding="utf-8"))
    if elementi is not None:
        analisi["elementi"] = elementi
    viste = {v["nome"]: v for v in json.loads((cartella / "viste.json").read_text(encoding="utf-8"))}
    maschere = calcola_maschere(analisi, viste)
    equi = cv2.imread(str(cartella / "originale_ridotto.jpg"))
    cv2.imwrite(str(cartella / "mappa.jpg"), immagine_mappa(equi, analisi["elementi"], maschere),
                [cv2.IMWRITE_JPEG_QUALITY, 88])
    return maschere


def conferma_mappa(cartella, categorie=None):
    """Applica le modifiche del fotografo alle categorie (id -> fisso/rinnova/togli) e salva la mappa confermata."""
    cartella = Path(cartella)
    analisi = json.loads((cartella / "analisi.json").read_text(encoding="utf-8"))
    for e in analisi["elementi"]:
        nuova = (categorie or {}).get(e["id"])
        if nuova in ("fisso", "rinnova", "togli"):
            e["categoria"] = nuova
            if nuova != "fisso":
                e["blocca_pixel"] = False
    (cartella / "mappa_confermata.json").write_text(json.dumps(analisi["elementi"], indent=2, ensure_ascii=False),
                                                    encoding="utf-8")
    disegna_mappa(cartella, analisi["elementi"])
    return analisi["elementi"]


# ------------------------------------------------------------------ FASE B

def genera(cartella, avanzamento=None):
    cartella = Path(cartella)
    impostazioni = carica_impostazioni()
    ai = impostazioni["ai"]
    _configura_log(cartella)
    fase = _fase(avanzamento)
    registro = _registro(cartella)
    t0 = time.time()
    fasi = {}

    scheda = json.loads((cartella / "richiesta.json").read_text(encoding="utf-8"))
    richiesta, modalita, percorso_360 = scheda["richiesta"], scheda.get("modalita", "rinnova"), scheda["foto"]
    analisi = Analisi.model_validate_json((cartella / "analisi.json").read_text(encoding="utf-8"))
    elementi = json.loads((cartella / "mappa_confermata.json").read_text(encoding="utf-8")) \
        if (cartella / "mappa_confermata.json").exists() else [e.model_dump() for e in analisi.elementi]
    viste = {v["nome"]: v for v in json.loads((cartella / "viste.json").read_text(encoding="utf-8"))}
    maschere = calcola_maschere({"elementi": elementi}, viste)
    equi_lavoro = cv2.imread(str(cartella / "originale_ridotto.jpg"))
    # in "rinnova" i contorni dei mobili attuali sono una guida utile; in "potenziale" no
    guida = disegno_linee(equi_lavoro, 3840, 1920) if modalita == "rinnova" else None
    if guida is not None:
        cv2.imwrite(str(cartella / "guida_linee.jpg"), guida)
    protetta = maschera_protetta(elementi, maschere, 3840, 1920)

    risultato, esiti, gen = None, [], None
    try:
        istruzioni_extra = ""
        migliore = None   # (voto, punteggio, immagine)
        for tentativo in range(1, ai["tentativi"] + 1):
            fase("ristrutturazione", f"Ristrutturazione del 360 (tentativo {tentativo})")
            t = time.time()
            gen = genera_360(equi_lavoro, analisi, ai, registro, cartella, istruzioni_extra, tentativo, modalita,
                             elementi=elementi, guida_linee=guida, protetta=protetta)
            punteggio, _ = punteggio_struttura(equi_lavoro, gen)
            log.info("Struttura rispettata: %.0f/100", punteggio)
            fasi["generazione"] = fasi.get("generazione", 0) + time.time() - t
            if punteggio < ai["punteggio_struttura_minimo"] and tentativo < ai["tentativi"]:
                log.warning("Architettura alterata: rifaccio subito senza correggere.")
                istruzioni_extra = ("The previous attempt changed the architecture. Keep every wall, corner, "
                                    "door, window and corridor at exactly the same pixel position.")
                continue

            t = time.time()
            fase("correzioni", "Correzione della giuntura del 360")
            gen = correggi_giuntura(gen, analisi, ai, registro, cartella)
            fase("correzioni", "Pulizia del pavimento sotto la fotocamera")
            gen = correggi_polo(gen, "nadir", analisi, ai, registro, cartella, raggio=0.18)
            fase("correzioni", "Blocco degli elementi fissi (pixel originali)")
            gen, bloccati = blocca_elementi_fissi(equi_lavoro, gen, elementi, maschere, cartella)
            non_bloccati = [b["nome"] for b in bloccati if not b["incollato"]]
            if non_bloccati:
                log.warning("Elementi fissi spostati dal modello (non reincollati): %s", ", ".join(non_bloccati))
            fasi["correzioni"] = fasi.get("correzioni", 0) + time.time() - t
            punteggio, mappa_s = punteggio_struttura(equi_lavoro, gen)
            if mappa_s is not None:
                cv2.imwrite(str(cartella / f"mappa_struttura_tentativo{tentativo}.jpg"), mappa_s)
            cv2.imwrite(str(cartella / f"risultato_tentativo{tentativo}.jpg"), gen, [cv2.IMWRITE_JPEG_QUALITY, 92])

            fase("qualita", f"Claude controlla il risultato (tentativo {tentativo})")
            t = time.time()
            registro.controlla(0.3, "controllo qualità")
            esito = controlla(equi_lavoro, gen, richiesta, analisi, punteggio, ai, registro, modalita, elementi)
            esiti.append({"tentativo": tentativo, "punteggio_struttura": round(punteggio, 1), **esito.model_dump()})
            (cartella / "controllo_qualita.json").write_text(json.dumps(esiti, indent=2, ensure_ascii=False),
                                                              encoding="utf-8")
            fasi["controllo"] = fasi.get("controllo", 0) + time.time() - t
            log.info("Tentativo %d: voto %d/10, struttura %.0f/100 - %s",
                     tentativo, esito.voto, punteggio, esito.giudizio)

            if migliore is None or (esito.voto, punteggio) > migliore[:2]:
                migliore = (esito.voto, punteggio, gen)
            if esito.voto >= ai["voto_minimo"] and not esito.rifare:
                break
            istruzioni_extra = esito.istruzioni_extra
        risultato = migliore[2] if migliore else gen
    except BudgetSuperato as e:
        log.error(str(e))
        risultato = (migliore[2] if migliore else gen) if "migliore" in locals() else gen
        if risultato is None:
            raise
        log.warning("Salvo l'ultimo risultato disponibile.")

    fase("consegna", "Salvataggio del JPG 360")
    originale = cv2.imread(str(percorso_360), cv2.IMREAD_COLOR)
    h_orig, w_orig = originale.shape[:2]
    finale = cv2.resize(risultato, (w_orig, h_orig), interpolation=cv2.INTER_LANCZOS4)
    percorso_finale = cartella / "risultato_360.jpg"
    salva_jpg_360(finale, str(percorso_finale), originale=str(percorso_360),
                  qualita=impostazioni["output"]["qualita_jpg"])
    anteprima = np.vstack([cv2.resize(originale, (2400, 1200), interpolation=cv2.INTER_AREA),
                           cv2.resize(risultato, (2400, 1200), interpolation=cv2.INTER_AREA)])
    cv2.imwrite(str(cartella / "prima_dopo.jpg"), anteprima, [cv2.IMWRITE_JPEG_QUALITY, 88])
    # immagini leggere per il viewer web (12K è troppo per molte schede video) e miniatura
    cv2.imwrite(str(cartella / "viewer_prima.jpg"), equi_lavoro, [cv2.IMWRITE_JPEG_QUALITY, 90])
    cv2.imwrite(str(cartella / "viewer_dopo.jpg"), cv2.resize(risultato, (4096, 2048), interpolation=cv2.INTER_CUBIC),
                [cv2.IMWRITE_JPEG_QUALITY, 90])
    cv2.imwrite(str(cartella / "miniatura.jpg"), cv2.resize(risultato, (800, 400), interpolation=cv2.INTER_AREA),
                [cv2.IMWRITE_JPEG_QUALITY, 85])

    tempi = json.loads((cartella / "tempi.json").read_text(encoding="utf-8")) if (cartella / "tempi.json").exists() else {}
    secondi_totali = tempi.get("prepara", 0) + (time.time() - t0)
    riepilogo = {
        "cartella": str(cartella), "risultato": str(percorso_finale),
        "minuti_totali": round(secondi_totali / 60, 1),
        "secondi_per_fase": {k: round(v) for k, v in fasi.items()},
        "chiamate": len(registro.chiamate),
        "costo_openai_euro": round(registro.totale_euro("openai"), 2),
        "costo_anthropic_euro": round(registro.totale_euro("anthropic"), 2),
        "costo_totale_euro": round(registro.totale_euro(), 2),
        "tentativi": len(esiti),
        "voto_finale": max((e["voto"] for e in esiti), default=None),
        "punteggio_struttura": max((e["punteggio_struttura"] for e in esiti), default=None),
        "modalita": modalita,
    }
    (cartella / "riepilogo.json").write_text(json.dumps(riepilogo, indent=2, ensure_ascii=False), encoding="utf-8")
    log.info("FINITO in %.1f min - costo %.2f € (OpenAI %.2f €, Claude %.2f €)",
             riepilogo["minuti_totali"], riepilogo["costo_totale_euro"],
             riepilogo["costo_openai_euro"], riepilogo["costo_anthropic_euro"])
    return riepilogo


def esegui(percorso_360, richiesta, avanzamento=None, cartella=None, modalita="rinnova"):
    """Tutto in un colpo (mappa confermata così com'è)."""
    cartella = Path(cartella or RADICE / "progetti" / nome_cartella(richiesta))
    prepara(percorso_360, richiesta, cartella, modalita, avanzamento)
    conferma_mappa(cartella)
    return genera(cartella, avanzamento)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    esegui(sys.argv[1], sys.argv[2])
