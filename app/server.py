"""
Server locale di PrimaVista 360 AI: serve la pagina web e fa partire i lavori.
Si avvia con avvia.bat e si usa dal browser su http://127.0.0.1:8360
"""
import json
import os
import shutil
import threading
import time
import traceback
from pathlib import Path

import cv2
import numpy as np
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .pipeline import esegui as pipeline
from .pipeline.p7_output import leggi_gpano

RADICE = Path(__file__).resolve().parents[1]
PROGETTI = RADICE / "progetti"
PROGETTI.mkdir(exist_ok=True)

app = FastAPI(title="PrimaVista 360 AI")


@app.middleware("http")
async def senza_cache(request, call_next):
    """Il browser ricarica sempre la versione più recente della pagina (utile dopo gli aggiornamenti)."""
    risposta = await call_next(request)
    risposta.headers["Cache-Control"] = "no-cache"
    return risposta

PRESET = [
    {"nome": "Bagno moderno", "testo": "Bagno moderno: gres effetto pietra chiara a pavimento e parete, mobile "
     "sospeso in legno rovere con lavabo integrato, specchio retroilluminato, doccia walk-in con vetro fisso, "
     "rubinetteria nera opaca."},
    {"nome": "Cucina", "testo": "Cucina moderna nella stessa posizione e con le stesse misure: ante opache "
     "chiare senza maniglie, top e alzatina in quartz effetto marmo, elettrodomestici da incasso, luce LED sotto i pensili."},
    {"nome": "Soggiorno", "testo": "Soggiorno moderno e luminoso: pavimento in rovere naturale a doghe larghe, "
     "pareti bianco caldo, divano in tessuto chiaro, tavolino basso, tappeto rettangolare, piantana, piante."},
    {"nome": "Camera", "testo": "Camera da letto moderna e accogliente: parquet rovere, pareti tortora chiaro, "
     "letto matrimoniale con testiera imbottita, comodini sospesi, lampade da tavolo, tende di lino."},
    {"nome": "Svuota stanza", "testo": "Svuota completamente la stanza: togli tutti i mobili e gli oggetti, "
     "lascia pavimento, pareti e soffitto puliti e rinnovati, pareti bianche, luce naturale."},
    {"nome": "Home staging", "testo": "Home staging arredato in stile contemporaneo neutro: toni caldi naturali, "
     "legno chiaro, tessuti beige, pochi complementi eleganti, piante verdi, luce calda."},
    {"nome": "Luxury marmo", "testo": "Stile moderno luxury, iper realistico. Pavimento in marmo Calacatta lucido, "
     "pareti lisce bianco caldo, finiture in ottone spazzolato, arredi in tessuto bouclé e noce."},
]

# Preset per ARREDA e RIPROGETTA: solo il TIPO di stanza e lo stile, MAI i mobili precisi.
# Quali mobili e di che misura (es. letto singolo o matrimoniale) li decide Claude dalle misure della stanza.
PRESET_ARREDO = [
    {"nome": "Camera", "testo": "Camera da letto contemporanea e accogliente, toni caldi, legno chiaro, tessili naturali. "
     "Scegli il letto e gli altri mobili in base allo spazio reale."},
    {"nome": "Cameretta", "testo": "Cameretta per ragazzi, luminosa e ordinata, colori tenui, legno chiaro. "
     "Scegli il letto, l'armadio e la scrivania in base allo spazio reale."},
    {"nome": "Soggiorno", "testo": "Soggiorno contemporaneo e luminoso, tessuti chiari, legno naturale, piante. "
     "Divano, tavolino e mobili proporzionati allo spazio reale."},
    {"nome": "Soggiorno con pranzo", "testo": "Soggiorno con zona pranzo, stile contemporaneo caldo. "
     "Numero di posti a tavola e misura del divano in base allo spazio reale."},
    {"nome": "Studio", "testo": "Studio o ufficio in casa, sobrio ed elegante, legno e toni neutri. "
     "Scrivania, seduta e libreria proporzionate allo spazio reale."},
    {"nome": "Sala da pranzo", "testo": "Sala da pranzo elegante, legno noce, luce calda. "
     "Tavolo e sedie in base allo spazio reale, con i passaggi liberi."},
    {"nome": "Neutro da vendita", "testo": "Home staging neutro da vendita: toni caldi naturali, legno chiaro, tessuti beige, "
     "pochi complementi eleganti, piante verdi. Arredo essenziale e proporzionato allo spazio reale."},
]

_lock = threading.Lock()


# ------------------------------------------------------------------ utilità

def _cartella(id_progetto):
    c = (PROGETTI / id_progetto).resolve()
    if c.parent != PROGETTI.resolve() or not c.is_dir():
        raise HTTPException(404, "Progetto non trovato")
    return c


def _leggi_json(percorso, predefinito=None):
    try:
        return json.loads(Path(percorso).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return predefinito


def _scrivi_stato(cartella, **campi):
    with _lock:
        stato = _leggi_json(cartella / "stato.json", {})
        stato.update(campi)
        (cartella / "stato.json").write_text(json.dumps(stato, ensure_ascii=False, indent=2), encoding="utf-8")


def _stato(cartella):
    stato = _leggi_json(cartella / "stato.json")
    if stato:
        return stato
    # progetti creati da riga di comando: si deduce lo stato dai file presenti
    if (cartella / "riepilogo.json").exists():
        return {"stato": "finito"}
    return {"stato": "sconosciuto"}


def _prepara_viewer(cartella):
    """Per i progetti vecchi crea le immagini leggere per il viewer se mancano."""
    if (cartella / "risultato_360.jpg").exists() and not (cartella / "viewer_dopo.jpg").exists():
        r = cv2.imread(str(cartella / "risultato_360.jpg"))
        cv2.imwrite(str(cartella / "viewer_dopo.jpg"), cv2.resize(r, (4096, 2048), interpolation=cv2.INTER_AREA))
        cv2.imwrite(str(cartella / "miniatura.jpg"), cv2.resize(r, (800, 400), interpolation=cv2.INTER_AREA))
    if not (cartella / "viewer_prima.jpg").exists():
        sorgente = cartella / "originale_ridotto.jpg"
        if not sorgente.exists():
            foto = Path((_leggi_json(cartella / "richiesta.json", {}) or {}).get("foto", ""))
            sorgente = foto if foto.is_absolute() else RADICE / foto
        img = cv2.imread(str(sorgente)) if sorgente.is_file() else None
        if img is not None:
            cv2.imwrite(str(cartella / "viewer_prima.jpg"), cv2.resize(img, (4096, 2048), interpolation=cv2.INTER_AREA))


def _stanze_della_casa(cid):
    """Le stanze già lavorate della stessa casa: [{nome, id}] nell'ordine della piantina."""
    if not cid or not (CASE / cid / "casa.json").exists():
        return []
    casa = _leggi_json(CASE / cid / "casa.json", {})
    stanze = casa.get("stanze", [])
    return [{"nome": stanze[int(i)]["nome"], "id": pid} for i, pid in sorted((casa.get("progetti") or {}).items(), key=lambda x: int(x[0]))
            if int(i) < len(stanze) and (PROGETTI / pid).exists()]


def _dettaglio(cartella):
    richiesta = _leggi_json(cartella / "richiesta.json", {}) or {}
    riepilogo = _leggi_json(cartella / "riepilogo.json")
    costi = _leggi_json(cartella / "costi.json", {}) or {}
    controlli = _leggi_json(cartella / "controllo_qualita.json", []) or []
    analisi = _leggi_json(cartella / "analisi.json")
    stato = _stato(cartella)
    if stato.get("stato") == "finito":
        _prepara_viewer(cartella)
    migliore = max(controlli, key=lambda c: (c.get("voto", 0), c.get("punteggio_struttura", 0)), default=None)
    return {
        "id": cartella.name,
        "richiesta": richiesta.get("richiesta", ""),
        "modalita": richiesta.get("modalita", "potenziale"),
        "nome_file": richiesta.get("nome_file") or Path(richiesta.get("foto", "")).name,
        "data": richiesta.get("data") or time.strftime("%d/%m/%Y %H:%M", time.localtime(cartella.stat().st_ctime)),
        "stato": stato,
        "riepilogo": riepilogo,
        "costo_euro": costi.get("totale_euro", 0),
        "costo_openai": costi.get("openai_euro", 0),
        "costo_claude": costi.get("anthropic_euro", 0),
        "chiamate": costi.get("numero_chiamate", 0),
        "controllo": migliore,
        "analisi": analisi,
        "versioni": _leggi_json(cartella / "versioni.json", []) or [],
        "servizio": richiesta.get("servizio", "rinnova"),
        "origine": richiesta.get("origine", "foto"),
        "svuotata": bool(richiesta.get("svuotata")),
        "servizio_scelto": richiesta.get("servizio_scelto", True),
        "casa": richiesta.get("casa"),
        "superfici": richiesta.get("superfici") or {},
        "stanza": richiesta.get("stanza", ""),
        "tipo_stanza": richiesta.get("tipo_stanza") or tipo_stanza(f"{richiesta.get('stanza', '')} {cartella.name}"),
        "casa_stanze": _stanze_della_casa(richiesta.get("casa")),
        "piantina": richiesta.get("piantina"),
        "varianti_pronte": sorted({p.stem.split("_")[-1] for p in cartella.glob("viewer_dopo_*.jpg")}),
        "file": {n: (cartella / n).exists() for n in
                 ("risultato_360.jpg", "prima_dopo.jpg", "viewer_prima.jpg", "viewer_dopo.jpg", "miniatura.jpg",
                  "mappa.jpg", "guida_controllo.jpg", "pianta.png", "controllo_bordi.jpg", "guida_inviata.jpg")},
    }


# ------------------------------------------------------------------ lavoro in background

def _avanzamento(cartella):
    def avanzamento(chiave, testo):
        _scrivi_stato(cartella, stato="in_corso", fase=chiave, testo=testo, aggiornato=time.time())
    return avanzamento


def _in_sicurezza(cartella, funzione):
    try:
        funzione()
    except Exception as e:  # noqa: BLE001
        (cartella / "errore.txt").write_text(traceback.format_exc(), encoding="utf-8")
        _scrivi_stato(cartella, stato="errore", testo=str(e))


def _lavora_prepara(cartella, percorso_foto, richiesta, modalita):
    """Fase A: analisi e mappa. Poi si aspetta la conferma del fotografo."""
    def fai():
        pipeline.prepara(percorso_foto, richiesta, cartella, modalita, _avanzamento(cartella))
        _scrivi_stato(cartella, stato="mappa_pronta", fase="conferma", testo="Controlla la mappa e conferma")
    _in_sicurezza(cartella, fai)


def _lavora_genera(cartella):
    """Fase B: generazione, correzioni, controllo, consegna."""
    def fai():
        pipeline.genera(cartella, _avanzamento(cartella))
        _scrivi_stato(cartella, stato="finito", fase="fine", testo="Consegna pronta")
    _in_sicurezza(cartella, fai)


def _avvia(funzione, *argomenti):
    threading.Thread(target=funzione, args=argomenti, daemon=True).start()


# ------------------------------------------------------------------ API

@app.get("/api/preset")
def preset():
    from .pipeline.p4_guidata import CORREZIONI, FASI
    return {"preset": PRESET, "preset_arredo": PRESET_ARREDO, "fasi": FASI, "correzioni": CORREZIONI}


# ------------------------------------------------------------------ CATALOGO DELL'IMPRESA

@app.get("/api/catalogo")
def catalogo_elenco():
    from . import catalogo
    return {"prodotti": catalogo.elenco(), "categorie": catalogo.CATEGORIE, "meshy": catalogo.meshy_disponibile(),
            "pose": catalogo.POSE, "finiture": catalogo.FINITURE}


@app.post("/api/catalogo")
async def catalogo_aggiungi(nome: str = Form(...), categoria: str = Form("Altro"), larghezza: int = Form(...),
                            profondita: int = Form(...), altezza: int = Form(...), quota: int = Form(0),
                            fornitore: str = Form(""), codice: str = Form(""), prezzo: str = Form(""), nota: str = Form(""),
                            rotazione_modello: int = Form(0), tipo: str = Form("prodotto"), finitura: str = Form("opaca"),
                            fuga_colore: str = Form("#b9b2a6"), fuga_mm: int = Form(2), posa: str = Form("dritta"),
                            foto_tipo: str = Form("piastrella"), tipo_luce: str = Form("faretto"), k: int = Form(3000),
                            calata: int = Form(70), led: str = Form(""), luce_specchio: str = Form(""), foto: UploadFile | None = File(None), modello: UploadFile | None = File(None)):
    from . import catalogo
    if not nome.strip() or min(larghezza, profondita, altezza) <= 0:
        raise HTTPException(400, "Servono il nome e le misure (larghezza, profondità, altezza in cm).")
    try:
        p = catalogo.aggiungi({"nome": nome, "categoria": categoria, "larghezza": larghezza, "profondita": profondita,
                               "altezza": altezza, "quota": quota, "fornitore": fornitore, "codice": codice,
                               "prezzo": prezzo, "nota": nota, "rotazione_modello": rotazione_modello, "tipo": tipo,
                               "finitura": finitura, "fuga_colore": fuga_colore, "fuga_mm": fuga_mm, "posa": posa,
                               "foto_tipo": foto_tipo, "tipo_luce": tipo_luce, "k": k, "calata": calata, "led": led,
                               "luce_specchio": luce_specchio},
                              (foto.filename, await foto.read()) if foto is not None and foto.filename else None,
                              (modello.filename, await modello.read()) if modello is not None and modello.filename else None)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return p


@app.post("/api/catalogo/{pid}/modello")
async def catalogo_modello(pid: str, modello: UploadFile = File(...)):
    from . import catalogo
    try:
        catalogo.carica_modello(pid, (modello.filename, await modello.read()))
    except (ValueError, KeyError) as e:
        raise HTTPException(400, str(e))
    return catalogo.prodotto(pid)


@app.post("/api/catalogo/{pid}/meshy")
def catalogo_meshy(pid: str):
    """Crea il modello 3D dalla foto con Meshy (consuma crediti Meshy). Parte solo dal clic dell'utente."""
    from . import catalogo
    try:
        catalogo.crea_da_foto(pid)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return catalogo.prodotto(pid)


@app.post("/api/catalogo/{pid}/modifica")
def catalogo_modifica(pid: str, dati: dict):
    from . import catalogo
    if not catalogo.prodotto(pid):
        raise HTTPException(404, "Prodotto non trovato.")
    try:
        catalogo.modifica(pid, dati)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return catalogo.prodotto(pid)


@app.delete("/api/catalogo/{pid}")
def catalogo_togli(pid: str):
    from . import catalogo
    catalogo.togli(pid)
    return {"ok": True}


@app.get("/api/catalogo/{pid}/file/{nome}")
def catalogo_file(pid: str, nome: str):
    from . import catalogo
    percorso = (catalogo.CARTELLA / pid / nome).resolve()
    if percorso.parent != (catalogo.CARTELLA / pid).resolve() or not percorso.is_file():
        raise HTTPException(404, "File non trovato")
    return FileResponse(percorso, headers={"Cache-Control": "no-cache"})


@app.post("/api/progetti")
async def nuovo_progetto(foto: UploadFile = File(...), richiesta: str = Form(""), modalita: str = Form("rinnova"),
                         servizio: str = Form(""), piantina: UploadFile | None = File(None),
                         stanza: str = Form("")):
    # percorso guidato: cosa fare (servizio) e stile si scelgono DOPO, nei passi del progetto
    scelto = servizio in ("rinnova", "prodotto", "riprogetta", "arreda")
    servizio = {"riprogetta": "arreda"}.get(servizio, servizio) if scelto else "rinnova"
    modalita = "potenziale" if servizio == "arreda" else "rinnova"
    richiesta = richiesta.strip()
    cartella = PROGETTI / pipeline.nome_cartella(stanza.strip() or richiesta or Path(foto.filename or "stanza").stem)
    cartella.mkdir(parents=True)
    estensione = Path(foto.filename or "foto.jpg").suffix.lower() or ".jpg"
    percorso = cartella / f"originale{estensione}"
    with open(percorso, "wb") as f:
        shutil.copyfileobj(foto.file, f)

    img = cv2.imread(str(percorso), cv2.IMREAD_REDUCED_COLOR_4)
    if img is None:
        shutil.rmtree(cartella, ignore_errors=True)
        raise HTTPException(400, "Il file non è un'immagine leggibile (serve un JPG).")
    h, w = img.shape[:2]
    if abs(w / h - 2) > 0.02:
        shutil.rmtree(cartella, ignore_errors=True)
        raise HTTPException(400, f"La foto non è un 360 equirettangolare (proporzioni {w}x{h}, serve 2:1).")

    # piantina insieme alla foto (facoltativa): dà le misure vere alla stanza della foto
    scheda = {"foto": str(percorso), "nome_file": foto.filename, "richiesta": richiesta, "modalita": modalita,
              "servizio": servizio, "servizio_scelto": scelto, "data": time.strftime("%d/%m/%Y %H:%M")}
    if piantina is not None and piantina.filename:
        est = Path(piantina.filename).suffix.lower()
        if est not in (".pdf", ".jpg", ".jpeg", ".png", ".webp"):
            shutil.rmtree(cartella, ignore_errors=True)
            raise HTTPException(400, "La piantina deve essere un PDF o un'immagine (JPG, PNG).")
        with open(cartella / f"piantina{est}", "wb") as f:
            shutil.copyfileobj(piantina.file, f)
        scheda.update({"piantina": f"piantina{est}", "stanza": stanza.strip()})
    # salva il nome originale del file nella scheda del progetto
    (cartella / "richiesta.json").write_text(json.dumps(scheda, ensure_ascii=False, indent=2), encoding="utf-8")
    _prepara_rilievo(cartella, percorso)
    return {"id": cartella.name}


# ------------------------------------------------------------------ CASA INTERA (piantina con più stanze)

CASE = RADICE / "case"


def _casa(cid):
    c = (CASE / cid).resolve()
    if c.parent != CASE.resolve() or not (c / "casa.json").exists():
        raise HTTPException(404, "Casa non trovata")
    return c


def _salva_casa(cartella, casa):
    (cartella / "casa.json").write_text(json.dumps(casa, ensure_ascii=False, indent=2), encoding="utf-8")


@app.post("/api/case")
async def nuova_casa(piantina: UploadFile = File(...)):
    """Piantina di una casa intera: Claude legge TUTTE le stanze (circa 0,05 €), poi l'impresa sceglie con un clic
    quali lavorare. Ogni stanza scelta diventa un progetto, collegato agli altri della stessa casa."""
    estensione = Path(piantina.filename or "piantina.jpg").suffix.lower()
    if estensione not in (".pdf", ".jpg", ".jpeg", ".png", ".webp"):
        raise HTTPException(400, "La piantina deve essere un PDF o un'immagine (JPG, PNG).")
    cid = time.strftime("casa_%Y%m%d_%H%M%S")
    cartella = CASE / cid
    cartella.mkdir(parents=True, exist_ok=True)
    percorso = cartella / f"piantina{estensione}"
    with open(percorso, "wb") as f:
        shutil.copyfileobj(piantina.file, f)
    if estensione != ".pdf" and cv2.imread(str(percorso)) is None:
        shutil.rmtree(cartella, ignore_errors=True)
        raise HTTPException(400, "Il file della piantina non è un'immagine leggibile.")
    _salva_casa(cartella, {"id": cid, "nome_file": piantina.filename, "piantina": percorso.name, "stato": "lettura",
                           "messaggio": "Claude legge le stanze della piantina", "stanze": [], "progetti": {}, "note": "",
                           "data": time.strftime("%d/%m/%Y %H:%M")})
    _avvia(_leggi_casa, cartella)
    return {"id": cid}


def _leggi_casa(cartella):
    from .pipeline.esegui import carica_impostazioni
    from .pipeline.p3_pianta import leggi_casa
    from .servizi.costi import RegistroCosti
    casa = _leggi_json(cartella / "casa.json", {})
    percorso = cartella / casa["piantina"]
    registro = RegistroCosti(cartella / "costi.json", os.getenv("SPESA_MASSIMA_EURO", "5"))
    try:
        if percorso.suffix.lower() == ".pdf":
            stanze, note = leggi_casa(percorso.read_bytes(), "pdf", carica_impostazioni()["ai"], registro)
        else:
            stanze, note = leggi_casa(cv2.imread(str(percorso)), "img", carica_impostazioni()["ai"], registro)
        casa.update({"stanze": stanze, "note": note, "stato": "pronta",
                     "messaggio": f"Trovate {len(stanze)} stanze"})
    except Exception as e:  # noqa: BLE001
        (cartella / "errore.txt").write_text(traceback.format_exc(), encoding="utf-8")
        casa.update({"stato": "errore", "messaggio": f"Non sono riuscito a leggere la piantina: {e}"})
    _salva_casa(cartella, casa)


@app.get("/api/case/{cid}")
def leggi_casa_api(cid: str):
    cartella = _casa(cid)
    casa = _leggi_json(cartella / "casa.json", {})
    casa["immagine"] = not casa.get("piantina", "").endswith(".pdf")
    # progetti già creati che esistono ancora
    casa["progetti"] = {k: v for k, v in (casa.get("progetti") or {}).items() if (PROGETTI / v).exists()}
    return casa


@app.get("/api/case/{cid}/file/{nome}")
def file_casa(cid: str, nome: str):
    cartella = _casa(cid)
    percorso = (cartella / nome).resolve()
    if percorso.parent != cartella or not percorso.is_file():
        raise HTTPException(404, "File non trovato")
    return FileResponse(percorso, headers={"Cache-Control": "no-cache"})


@app.post("/api/case/{cid}/stanze")
def scegli_stanze(cid: str, dati: dict):
    """Le stanze scelte con un clic diventano progetti (uno per stanza), già costruiti in scala dalla lettura della casa."""
    cartella = _casa(cid)
    casa = _leggi_json(cartella / "casa.json", {})
    indici = [int(i) for i in dati.get("indici", []) if 0 <= int(i) < len(casa.get("stanze", []))]
    if not indici:
        raise HTTPException(400, "Scegli almeno una stanza.")
    progetti = casa.setdefault("progetti", {})
    for i in indici:
        if str(i) in progetti and (PROGETTI / progetti[str(i)]).exists():
            continue
        stanza = casa["stanze"][i]
        cartella_p = PROGETTI / pipeline.nome_cartella(stanza["nome"])
        while cartella_p.exists():
            time.sleep(1.1)
            cartella_p = PROGETTI / pipeline.nome_cartella(stanza["nome"])
        cartella_p.mkdir(parents=True)
        shutil.copy2(cartella / casa["piantina"], cartella_p / casa["piantina"])
        (cartella_p / "richiesta.json").write_text(json.dumps(
            {"foto": str(cartella_p / "originale.jpg"), "nome_file": casa.get("nome_file"), "richiesta": "",
             "modalita": "potenziale", "servizio": "arreda", "servizio_scelto": True, "origine": "piantina",
             "piantina": casa["piantina"], "stanza": stanza["nome"], "casa": cid,
             "data": time.strftime("%d/%m/%Y %H:%M")}, ensure_ascii=False, indent=2), encoding="utf-8")
        _scrivi_stato(cartella_p, stato="in_corso", fase="rilievo_auto", testo=f"Costruisco {stanza['nome']} in scala",
                      avvio=time.time())
        _avvia(_costruisci_stanza_casa, cartella_p, {k: v for k, v in stanza.items() if k != "riquadro"})
        progetti[str(i)] = cartella_p.name
    _salva_casa(cartella, casa)
    return {"progetti": [progetti[str(i)] for i in indici]}


def _costruisci_stanza_casa(cartella, pianta):
    try:
        salva_stanza(cartella.name, {"pianta": pianta, "mobili": [], "varianti": {"A": []}, "variante": "A"}, disegna=1)
        _scrivi_stato(cartella, stato="rilievo", fase="rilievo",
                      testo="Stanza pronta" + (f" · {pianta['note']}" if pianta.get("note") else ""))
    except Exception as e:  # noqa: BLE001
        (cartella / "errore_rilievo.txt").write_text(traceback.format_exc(), encoding="utf-8")
        _scrivi_stato(cartella, stato="rilievo", fase="rilievo", testo=f"Stanza da controllare: {e}")


@app.post("/api/progetti/da-piantina")
async def nuovo_da_piantina(piantina: UploadFile = File(...), stanza: str = Form(""), richiesta: str = Form("")):
    """Progetto SENZA foto 360: Claude legge la piantina (circa 0,02 €), il programma costruisce la stanza in scala."""
    estensione = Path(piantina.filename or "piantina.jpg").suffix.lower()
    if estensione not in (".pdf", ".jpg", ".jpeg", ".png", ".webp"):
        raise HTTPException(400, "La piantina deve essere un PDF o un'immagine (JPG, PNG).")
    cartella = PROGETTI / pipeline.nome_cartella(f"{stanza or 'stanza'} {richiesta}".strip())
    cartella.mkdir(parents=True)
    percorso = cartella / f"piantina{estensione}"
    with open(percorso, "wb") as f:
        shutil.copyfileobj(piantina.file, f)
    if estensione != ".pdf" and cv2.imread(str(percorso)) is None:
        shutil.rmtree(cartella, ignore_errors=True)
        raise HTTPException(400, "Il file della piantina non è un'immagine leggibile.")
    (cartella / "richiesta.json").write_text(json.dumps(
        {"foto": str(cartella / "originale.jpg"), "nome_file": piantina.filename, "richiesta": richiesta.strip(),
         "modalita": "potenziale", "servizio": "arreda", "origine": "piantina", "piantina": percorso.name,
         "stanza": stanza.strip(), "data": time.strftime("%d/%m/%Y %H:%M")}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    _scrivi_stato(cartella, stato="in_corso", fase="rilievo_auto", testo="Claude legge la piantina",
                  avvio=time.time())
    _avvia(_leggi_piantina, cartella, percorso, stanza.strip())
    return {"id": cartella.name}


def _leggi_piantina(cartella, percorso, stanza):
    from .pipeline.esegui import carica_impostazioni
    from .pipeline.p3_pianta import leggi_pianta
    from .servizi.costi import RegistroCosti
    registro = RegistroCosti(cartella / "costi.json", os.getenv("SPESA_MASSIMA_EURO", "5"))
    try:
        if percorso.suffix.lower() == ".pdf":
            pianta = leggi_pianta(percorso.read_bytes(), "pdf", stanza, carica_impostazioni()["ai"], registro)
        else:
            pianta = leggi_pianta(cv2.imread(str(percorso)), "img", stanza, carica_impostazioni()["ai"], registro)
        dati = {"pianta": pianta, "mobili": [], "varianti": {"A": []}, "variante": "A", "fissi": [],
                "angoli": [], "spigoli": [], "pareti": {}, "soffitto": None, "altezza_camera": 1.5}
        salva_stanza(cartella.name, dati, disegna=1)
        testo = "Stanza pronta" + (f" · {pianta['note']}" if pianta.get("note") else "")
    except Exception as e:  # noqa: BLE001
        (cartella / "errore_rilievo.txt").write_text(traceback.format_exc(), encoding="utf-8")
        testo = f"Non sono riuscito a leggere la piantina ({e}): inserisci le misure a mano"
        salva_stanza(cartella.name, {"pianta": {"nome": stanza or "Stanza", "larghezza": 350, "profondita": 400,
                                                "altezza": 270, "camera": [175, 200], "camera_h": 150,
                                                "aperture": []},
                                     "mobili": [], "varianti": {"A": []}, "variante": "A"}, disegna=1)
    _scrivi_stato(cartella, stato="rilievo", fase="rilievo", testo=testo)


def _base_da_piantina(cartella, s):
    """Stanza da piantina: la "foto" è la base geometrica (il modellino 360 con i mobili a misura)."""
    from .pipeline.p3_guida import guida_pulita
    from .pipeline.p7_output import salva_jpg_360
    base, _ = guida_pulita(s, 4096)
    cv2.imwrite(str(cartella / "viewer_prima.jpg"), base, [cv2.IMWRITE_JPEG_QUALITY, 92])
    cv2.imwrite(str(cartella / "originale_ridotto.jpg"), base, [cv2.IMWRITE_JPEG_QUALITY, 92])
    cv2.imwrite(str(cartella / "miniatura.jpg"), cv2.resize(base, (800, 400), interpolation=cv2.INTER_AREA),
                [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not (cartella / "originale.jpg").exists():
        # dimensione del 360 finale (8K): il risultato viene portato a questa larghezza con la nitidezza AI
        salva_jpg_360(cv2.resize(base, (7680, 3840), interpolation=cv2.INTER_NEAREST), str(cartella / "originale.jpg"),
                      qualita=90)
    return base


# ------------------------------------------------------------------ RILIEVO (senza AI)

def _prepara_rilievo(cartella, percorso_foto, stanza_precedente=None):
    """Prepara il progetto per il rilievo manuale: copia ridotta della foto per il viewer. Nessuna AI."""
    img = cv2.imread(str(percorso_foto), cv2.IMREAD_COLOR)
    ridotta = cv2.resize(img, (4096, 2048), interpolation=cv2.INTER_AREA)
    cv2.imwrite(str(cartella / "originale_ridotto.jpg"), ridotta, [cv2.IMWRITE_JPEG_QUALITY, 92])
    cv2.imwrite(str(cartella / "viewer_prima.jpg"), ridotta, [cv2.IMWRITE_JPEG_QUALITY, 90])
    cv2.imwrite(str(cartella / "miniatura.jpg"), cv2.resize(ridotta, (800, 400), interpolation=cv2.INTER_AREA),
                [cv2.IMWRITE_JPEG_QUALITY, 85])
    if stanza_precedente:
        (cartella / "stanza_input.json").write_text(json.dumps(stanza_precedente, ensure_ascii=False, indent=2),
                                                    encoding="utf-8")
        _scrivi_stato(cartella, stato="rilievo", fase="rilievo", testo="Rilievo della stanza", avvio=time.time())
        return
    _scrivi_stato(cartella, stato="in_corso", fase="rilievo_auto", testo="Rilievo automatico della stanza",
                  avvio=time.time())
    _avvia(_rilievo_automatico, cartella, ridotta)


def _rilievo_automatico(cartella, equi):
    """HorizonNet trova la stanza (gratis, sul PC); poi si disegnano misure e guida.
    Se il modello non c'è o non ci riesce, si passa al rilievo a mano."""
    from .pipeline import p3_auto
    testo = "Stanza pronta"
    try:
        if not p3_auto.disponibile():
            raise RuntimeError("modello HorizonNet non installato")
        trovato = p3_auto.trova_stanza(equi)
        dati = {"altezza_camera": 1.5, "inclinazione": {"pitch": 0, "roll": 0}, "angoli": trovato["angoli"],
                "spigoli": [], "pareti": {}, "soffitto": trovato["soffitti"][0] if trovato["soffitti"] else None,
                "fissi": [], "mobili": [], "automatico": True}
        salva_stanza(cartella.name, dati, disegna=1)
    except Exception as e:  # noqa: BLE001
        (cartella / "errore_rilievo.txt").write_text(traceback.format_exc(), encoding="utf-8")
        testo = f"Rilievo automatico non riuscito ({e}): fai il rilievo a mano"
    scheda = _leggi_json(cartella / "richiesta.json", {}) or {}
    if scheda.get("piantina") and (cartella / "room.json").exists():
        _scrivi_stato(cartella, stato="in_corso", fase="rilievo_auto", testo="Claude legge le misure dalla piantina")
        testo = _tara_con_piantina(cartella, scheda) or testo
    _scrivi_stato(cartella, stato="rilievo", fase="rilievo", testo=testo)


def _tara_con_piantina(cartella, scheda):
    """Foto 360 + piantina: la forma della stanza viene dalla foto, la SCALA dalle misure della piantina.
    Tutte le misure ricavate dalla foto sono proporzionali all'altezza della fotocamera: la si corregge
    in modo che larghezza e profondità coincidano con la piantina (in media)."""
    from .pipeline.esegui import carica_impostazioni
    from .pipeline.p3_pianta import leggi_pianta
    from .pipeline.p3_stanza import costruisci
    from .servizi.costi import RegistroCosti
    registro = RegistroCosti(cartella / "costi.json", os.getenv("SPESA_MASSIMA_EURO", "5"))
    registro.chiamate = (_leggi_json(cartella / "costi.json", {}) or {}).get("chiamate", [])
    percorso = cartella / scheda["piantina"]
    try:
        ai = carica_impostazioni()["ai"]
        if percorso.suffix.lower() == ".pdf":
            pianta = leggi_pianta(percorso.read_bytes(), "pdf", scheda.get("stanza", ""), ai, registro)
        else:
            pianta = leggi_pianta(cv2.imread(str(percorso)), "img", scheda.get("stanza", ""), ai, registro)
        dati = _leggi_json(cartella / "stanza_input.json", {}) or {}
        s = costruisci(dati)
        if "errore" in s:
            return None
        foto_m = sorted([s["XR"] - s["XL"], s["ZW"] - s["ZB"]])
        pianta_m = sorted([pianta["larghezza"] / 100, pianta["profondita"] / 100])
        k = (pianta_m[0] / foto_m[0] + pianta_m[1] / foto_m[1]) / 2
        forma = abs((foto_m[1] / foto_m[0]) / (pianta_m[1] / pianta_m[0]) - 1)
        dati.update({"altezza_camera": round(s["h"] * k, 3), "tara_soffitto": False, "tara_porta": False,
                     "altezza_soffitto": pianta.get("altezza", 270) / 100, "misure_piantina": pianta})
        salva_stanza(cartella.name, dati, disegna=1)
        testo = f"Misure dalla piantina: {pianta['larghezza']} × {pianta['profondita']} cm"
        if forma > 0.10:
            testo += (f" · attenzione: la forma della stanza nella foto e nella piantina differisce del {round(forma * 100)}%,"
                      " controlla che sia la stanza giusta")
        return testo
    except Exception as e:  # noqa: BLE001  la foto resta comunque utilizzabile con la taratura dal soffitto
        (cartella / "errore_piantina.txt").write_text(traceback.format_exc(), encoding="utf-8")
        return f"Piantina non letta ({e}): misure stimate dalla foto"


def _foto_in_bolla(cartella, pitch, roll):
    """Crea (se serve) la versione in bolla della foto e la usa per viewer e guida."""
    from .pipeline.geometria import metti_in_bolla
    base = cv2.imread(str(cartella / "originale_ridotto.jpg"))
    livellata = metti_in_bolla(base, pitch, roll)
    cv2.imwrite(str(cartella / "viewer_prima.jpg"), livellata, [cv2.IMWRITE_JPEG_QUALITY, 90])
    return livellata


@app.get("/api/presets-rilievo")
def presets_rilievo():
    from .pipeline.p3_stanza import PRESET_MOBILI, TIPI_FISSI
    return {"mobili": PRESET_MOBILI, "fissi": list(TIPI_FISSI)}


@app.get("/api/progetti/{id_progetto}/stanza")
def leggi_stanza(id_progetto: str):
    from .pipeline.p3_stanza import affidabile
    cartella = _cartella(id_progetto)
    stanza = _leggi_json(cartella / "room.json")
    return {"input": _leggi_json(cartella / "stanza_input.json", {}) or {},
            "stanza": stanza, "affidabile": affidabile(stanza) if stanza else None,
            "guida": (cartella / "guida_controllo.jpg").exists(),
            "linee": (cartella / "guida_linee.jpg").exists()}


@app.post("/api/progetti/{id_progetto}/stanza")
def salva_stanza(id_progetto: str, dati: dict, disegna: int = 0):
    """Ricalcola la stanza dai clic del fotografo. Con disegna=1 rifà anche le guide radar (qualche secondo)."""
    from .pipeline.p3_guida import guida_controllo, guida_pulita, pianta
    from .pipeline.p3_stanza import costruisci, serializza
    cartella = _cartella(id_progetto)
    precedente = _leggi_json(cartella / "stanza_input.json", {}) or {}
    (cartella / "stanza_input.json").write_text(json.dumps(dati, ensure_ascii=False, indent=2), encoding="utf-8")
    incl, incl_prec = dati.get("inclinazione", {}), precedente.get("inclinazione", {})
    if incl != incl_prec and not dati.get("pianta"):
        _foto_in_bolla(cartella, float(incl.get("pitch", 0)), float(incl.get("roll", 0)))
    s = costruisci(dati)
    if "errore" in s:
        return {"errore": s["errore"]}
    if dati.get("pianta") and disegna:
        _base_da_piantina(cartella, s)
    (cartella / "room.json").write_text(json.dumps(serializza(s), ensure_ascii=False, indent=2), encoding="utf-8")
    cv2.imwrite(str(cartella / "pianta.png"), pianta(s))
    if disegna:
        foto = cv2.imread(str(cartella / "viewer_prima.jpg"))
        pulita, rc = guida_pulita(s, 4096)
        controllo, _ = guida_controllo(s, foto, 4096, rc=rc)
        cv2.imwrite(str(cartella / "guida_pulita.jpg"), pulita, [cv2.IMWRITE_JPEG_QUALITY, 90])
        cv2.imwrite(str(cartella / "guida_controllo.jpg"), controllo, [cv2.IMWRITE_JPEG_QUALITY, 90])
        if not dati.get("pianta"):
            _linee_pareti(cartella, s, foto)
    from .pipeline.p3_stanza import affidabile
    out = serializza(s)
    return {"stanza": out, "affidabile": affidabile(out)}


def _linee_pareti(cartella, s, foto):
    """Foto con SOLO le linee della stanza trovata (angoli tra pareti, pavimento, soffitto) in oro:
    serve al passo "La stanza" per controllare a colpo d'occhio che le pareti siano al posto giusto."""
    from .pipeline.p3_guida import _spigoli_stanza, ray_casting
    rc = ray_casting({**s, "mobili": []}, 4096)          # i mobili nuovi non devono coprire le linee
    linee = cv2.dilate(_spigoli_stanza({**s, "mobili": []}, rc).astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    out = cv2.resize(foto, (4096, 2048), interpolation=cv2.INTER_AREA)
    out[linee] = (65, 179, 227)
    cv2.imwrite(str(cartella / "guida_linee.jpg"), out, [cv2.IMWRITE_JPEG_QUALITY, 90])


def _lavora_guidata(cartella, correzione=None, variante=None):
    """Generazione guidata (foto + guida + prompt strutturato) in background."""
    from .pipeline import p4_guidata

    def fai():
        p4_guidata.genera(cartella, _avanzamento(cartella), correzione, variante)
        _scrivi_stato(cartella, stato="finito", fase="fine", testo="Consegna pronta")
    _in_sicurezza(cartella, fai)


@app.post("/api/progetti/{id_progetto}/genera")
def genera_guidata(id_progetto: str, dati: dict | None = None):
    """Parte SOLO quando il fotografo clicca 'Genera il 360' (costa circa 0,20-0,35 €)."""
    cartella = _cartella(id_progetto)
    if not (cartella / "room.json").exists():
        raise HTTPException(400, "Prima completa e conferma il rilievo.")
    if _stato(cartella).get("stato") == "in_corso":
        raise HTTPException(400, "C'è già un lavoro in corso su questo progetto.")
    # niente spesa con una stanza ricostruita male: ChatGPT riceverebbe una guida sbagliata
    from .pipeline.p3_stanza import affidabile
    # (solo per Arreda: l'arredo si progetta sulle misure della stanza)
    servizio = (_leggi_json(cartella / "richiesta.json", {}) or {}).get("servizio")
    if servizio == "arreda" and not affidabile(_leggi_json(cartella / "room.json")):
        raise HTTPException(400, "La stanza non è stata misurata bene (troppi mobili per il rilievo automatico): "
                                 "non genero per non spendere su un risultato sbagliato. Sistemala in Strumenti avanzati → Sposta linee.")
    _scrivi_stato(cartella, stato="in_corso", fase="preparazione", testo="Avvio", avvio=time.time())
    _avvia(_lavora_guidata, cartella, None, (dati or {}).get("variante"))
    return {"ok": True}


@app.post("/api/progetti/{id_progetto}/correggi")
def correggi(id_progetto: str, dati: dict):
    """Rimanda a ChatGPT una delle frasi di correzione pronte (o un testo libero)."""
    cartella = _cartella(id_progetto)
    if not list(cartella.glob("risultato*_v*.jpg")):
        raise HTTPException(400, "Non c'è ancora un risultato da correggere.")
    if _stato(cartella).get("stato") == "in_corso":
        raise HTTPException(400, "C'è già un lavoro in corso su questo progetto.")
    correzione = (dati.get("chiave") or dati.get("testo") or "").strip()
    if not correzione:
        raise HTTPException(400, "Scegli una correzione.")
    _scrivi_stato(cartella, stato="in_corso", fase="preparazione", testo="Avvio correzione", avvio=time.time())
    _avvia(_lavora_guidata, cartella, correzione, dati.get("variante"))
    return {"ok": True}


# ------------------------------------------------------------------ PRODOTTI REALI E MATERIALI

DESTINAZIONI = {"mobile", "pavimento", "pareti", "parete_fondo", "parete_destra", "parete_dietro", "parete_sinistra",
                "rivestimento", "soffitto", "porte", "moodboard"}


def _riferimenti(cartella):
    return _leggi_json(cartella / "riferimenti.json", []) or []


@app.get("/api/progetti/{id_progetto}/riferimenti")
def elenco_riferimenti(id_progetto: str):
    return {"riferimenti": _riferimenti(_cartella(id_progetto))}


@app.post("/api/progetti/{id_progetto}/riferimenti")
async def carica_riferimento(id_progetto: str, foto: UploadFile = File(...), destinazione: str = Form(...),
                             mobile: str = Form(""), nota: str = Form(""), altezza_cm: int = Form(0)):
    """Foto di un prodotto vero (per un mobile del rilievo) o di un materiale (pavimento, pareti, moodboard)."""
    cartella = _cartella(id_progetto)
    if destinazione not in DESTINAZIONI:
        raise HTTPException(400, "Destinazione non valida.")
    if destinazione == "mobile" and not mobile:
        raise HTTPException(400, "Indica a quale mobile si riferisce la foto.")
    elenco = _riferimenti(cartella)
    stessi = [r for r in elenco if r["destinazione"] == destinazione and r.get("mobile", "") == mobile]
    if len(stessi) >= 4:
        raise HTTPException(400, "Massimo 4 foto per ogni mobile o materiale.")
    if len(elenco) >= 10:
        raise HTTPException(400, "Massimo 10 foto di riferimento per progetto.")
    dati = await foto.read()
    img = cv2.imdecode(np.frombuffer(dati, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise HTTPException(400, "Il file non è un'immagine leggibile (JPG o PNG).")
    # ridotta a 1536 px sul lato lungo: basta per il modello e costa meno
    h, w = img.shape[:2]
    scala = min(1.0, 1536 / max(h, w))
    if scala < 1:
        img = cv2.resize(img, (int(w * scala), int(h * scala)), interpolation=cv2.INTER_AREA)
    (cartella / "riferimenti").mkdir(exist_ok=True)
    rid = f"rif_{int(time.time() * 1000)}"
    cv2.imwrite(str(cartella / "riferimenti" / f"{rid}.jpg"), img, [cv2.IMWRITE_JPEG_QUALITY, 92])
    elenco.append({"id": rid, "file": f"riferimenti/{rid}.jpg", "destinazione": destinazione, "mobile": mobile,
                   "nota": nota.strip(), "nome_file": foto.filename,
                   "altezza_cm": altezza_cm or (120 if destinazione == "rivestimento" else 0)})
    (cartella / "riferimenti.json").write_text(json.dumps(elenco, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"riferimenti": elenco}


@app.post("/api/progetti/{id_progetto}/riferimenti/{rid}/nota")
def nota_riferimento(id_progetto: str, rid: str, dati: dict):
    cartella = _cartella(id_progetto)
    elenco = _riferimenti(cartella)
    for r in elenco:
        if r["id"] == rid:
            r["nota"] = (dati.get("nota") or "").strip()
    (cartella / "riferimenti.json").write_text(json.dumps(elenco, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"riferimenti": elenco}


@app.delete("/api/progetti/{id_progetto}/riferimenti/{rid}")
def togli_riferimento(id_progetto: str, rid: str):
    cartella = _cartella(id_progetto)
    elenco = [r for r in _riferimenti(cartella) if r["id"] != rid]
    (cartella / "riferimenti.json").write_text(json.dumps(elenco, ensure_ascii=False, indent=2), encoding="utf-8")
    (cartella / "riferimenti" / f"{rid}.jpg").unlink(missing_ok=True)
    return {"riferimenti": elenco}


@app.get("/api/progetti/{id_progetto}/riferimenti/{rid}.jpg")
def foto_riferimento(id_progetto: str, rid: str):
    percorso = (_cartella(id_progetto) / "riferimenti" / f"{rid}.jpg").resolve()
    if not percorso.is_file():
        raise HTTPException(404, "Foto non trovata")
    return FileResponse(percorso)


TIPI_STANZA = ["bagno", "cucina", "camera", "soggiorno", "altro"]


def tipo_stanza(nome):
    """Tipo di stanza dal nome (es. "Bagno principale" -> bagno): decide cosa mostra la pagina di lavoro."""
    n = (nome or "").lower()
    for tipo, parole in (("bagno", ("bagno", "wc", "servizi", "doccia", "lavanderia")),
                         ("cucina", ("cucina", "cottura", "cucinino")),
                         ("camera", ("camera", "letto", "cameretta")),
                         ("soggiorno", ("soggiorno", "salotto", "living", "sala", "pranzo"))):
        if any(p in n for p in parole):
            return tipo
    return "altro"


@app.post("/api/progetti/{id_progetto}/scheda")
def aggiorna_scheda(id_progetto: str, dati: dict):
    """Percorso guidato: salva la scelta "Cosa vuoi fare" (servizio) e lo stile / le note (richiesta)."""
    cartella = _cartella(id_progetto)
    scheda = _leggi_json(cartella / "richiesta.json", {}) or {}
    if "servizio" in dati:
        servizio = {"riprogetta": "arreda"}.get(dati["servizio"], dati["servizio"])
        if servizio not in ("rinnova", "prodotto", "arreda"):
            raise HTTPException(400, "Scelta non valida.")
        if scheda.get("origine") == "piantina" and servizio != "arreda":
            raise HTTPException(400, "Con la sola piantina si può solo progettare la stanza.")
        scheda.update({"servizio": servizio, "servizio_scelto": True,
                       "modalita": "potenziale" if servizio == "arreda" else "rinnova"})
    if "richiesta" in dati:
        scheda["richiesta"] = str(dati["richiesta"])[:3000]
    if dati.get("tipo_stanza") in TIPI_STANZA:
        scheda["tipo_stanza"] = dati["tipo_stanza"]
    if "superfici" in dati:
        # piastrelle e pitture per zona (pavimento, pareti, rivestimento, doccia, soffitto) per il motore 3D
        scheda["superfici"] = {k: v for k, v in (dati["superfici"] or {}).items() if isinstance(v, dict)}
    (cartella / "richiesta.json").write_text(json.dumps(scheda, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "servizio": scheda.get("servizio"), "richiesta": scheda.get("richiesta", "")}


@app.post("/api/progetti/{id_progetto}/anteprima3d")
def anteprima_3d(id_progetto: str, dati: dict | None = None):
    """Anteprima veloce del render 3D (pochi secondi, gratis): stesso motore del 360 finale, a bassa risoluzione.
    Serve a controllare posizione e aspetto dei prodotti veri mentre si progetta."""
    from .motore3d.render import prepara, render
    from .pipeline.p3_stanza import costruisci, serializza
    cartella = _cartella(id_progetto)
    scheda = _leggi_json(cartella / "richiesta.json", {}) or {}
    ingresso = _leggi_json(cartella / "stanza_input.json", {}) or {}
    variante = (dati or {}).get("variante")
    if variante and (ingresso.get("varianti") or {}).get(variante) is not None:
        ingresso["mobili"] = ingresso["varianti"][variante]
    s = costruisci(ingresso)
    if "errore" in s:
        raise HTTPException(400, s["errore"])
    png = cartella / "anteprima3d.png"
    try:
        secondi = render(prepara(serializza(s), scheda.get("richiesta", ""), scheda.get("superfici")), png, larghezza=1536, campioni=32)
    except RuntimeError as e:
        raise HTTPException(500, str(e))
    cv2.imwrite(str(cartella / "anteprima3d.jpg"), cv2.imread(str(png)), [cv2.IMWRITE_JPEG_QUALITY, 90])
    return {"secondi": round(secondi, 1)}


@app.post("/api/progetti/{id_progetto}/svuota")
def svuota_stanza(id_progetto: str):
    """Svuota il 360 arredato con ChatGPT (circa 0,10-0,25 €): la stanza vuota diventa la base del progetto."""
    cartella = _cartella(id_progetto)
    if _stato(cartella).get("stato") == "in_corso":
        raise HTTPException(400, "C'è già un lavoro in corso su questo progetto.")
    if (_leggi_json(cartella / "richiesta.json", {}) or {}).get("origine") == "piantina":
        raise HTTPException(400, "La stanza da piantina è già vuota.")
    _scrivi_stato(cartella, stato="in_corso", fase="svuota", testo="ChatGPT svuota la stanza", avvio=time.time())
    _avvia(_lavora_svuota, cartella)
    return {"ok": True}


def _lavora_svuota(cartella):
    from .pipeline.p4_svuota import svuota
    try:
        vuota = svuota(cartella, _avanzamento(cartella))
        scheda = _leggi_json(cartella / "richiesta.json", {}) or {}
        scheda["svuotata"] = True
        (cartella / "richiesta.json").write_text(json.dumps(scheda, ensure_ascii=False, indent=2), encoding="utf-8")
        _scrivi_stato(cartella, stato="in_corso", fase="svuota", testo="Misuro la stanza vuota")
        _rilievo_automatico(cartella, vuota)          # senza mobili il rilievo è più preciso
    except Exception as e:  # noqa: BLE001  il progetto resta com'era, si può riprovare
        (cartella / "errore.txt").write_text(traceback.format_exc(), encoding="utf-8")
        _scrivi_stato(cartella, stato="rilievo", fase="rilievo", testo=f"Svuotamento non riuscito: {e}")


@app.post("/api/progetti/{id_progetto}/proponi-arredo")
def proponi_arredo(id_progetto: str, dati: dict | None = None):
    """Claude propone l'arredo a misura per la stanza (circa 0,05-0,15 €). Il programma la verifica."""
    from .pipeline.p3_arredo import proponi
    from .pipeline.esegui import carica_impostazioni
    from .servizi.costi import RegistroCosti
    cartella = _cartella(id_progetto)
    ingresso = _leggi_json(cartella / "stanza_input.json", {}) or {}
    scheda = _leggi_json(cartella / "richiesta.json", {}) or {}
    registro = RegistroCosti(cartella / "costi.json", os.getenv("SPESA_MASSIMA_EURO", "5"))
    registro.chiamate = (_leggi_json(cartella / "costi.json", {}) or {}).get("chiamate", [])
    foto = cv2.imread(str(cartella / "viewer_prima.jpg"))
    richiesta = (dati or {}).get("richiesta") or scheda.get("richiesta", "")
    try:
        prima = cartella / "originale_ridotto_arredata.jpg"
        mobili, ragionamento, problemi = proponi(ingresso, foto, richiesta, carica_impostazioni()["ai"], registro,
                                                 scheda.get("servizio", "arreda"),
                                                 cv2.imread(str(prima)) if prima.exists() else None)
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    return {"mobili": mobili, "ragionamento": ragionamento, "problemi": problemi,
            "costo_euro": round(registro.totale_euro(), 2)}


@app.post("/api/progetti/{id_progetto}/conferma-rilievo")
def conferma_rilievo(id_progetto: str):
    cartella = _cartella(id_progetto)
    if not (cartella / "room.json").exists():
        raise HTTPException(400, "Prima completa il rilievo (angoli del pavimento).")
    _scrivi_stato(cartella, stato="rilievo_confermato", fase="rilievo", testo="Rilievo confermato")
    return {"ok": True}


@app.post("/api/controlla-foto")
async def controlla_foto(foto: UploadFile = File(...)):
    """Controllo rapido prima di partire: dimensioni e metadati 360."""
    temporaneo = PROGETTI / f"_tmp_{int(time.time() * 1000)}.jpg"
    with open(temporaneo, "wb") as f:
        shutil.copyfileobj(foto.file, f)
    try:
        img = cv2.imread(str(temporaneo), cv2.IMREAD_REDUCED_COLOR_8)
        if img is None:
            return {"ok": False, "messaggi": ["Il file non è un'immagine leggibile."]}
        from PIL import Image
        with Image.open(temporaneo) as im:
            w, h = im.size
        gpano = leggi_gpano(str(temporaneo))
        messaggi, ok = [], True
        if abs(w / h - 2) > 0.02:
            ok = False
            messaggi.append(f"Proporzioni {w}×{h}: non è un 360 equirettangolare (serve 2:1).")
        if w < 5000:
            messaggi.append(f"Risoluzione {w}px: va bene, ma sopra i 5.7K il risultato è più nitido.")
        if not gpano:
            messaggi.append("Nel file non ci sono metadati 360: li aggiungo io nel risultato.")
        return {"ok": ok, "larghezza": w, "altezza": h, "metadati_360": bool(gpano),
                "fotocamera": gpano.get("CaptureSoftware", ""), "messaggi": messaggi}
    finally:
        temporaneo.unlink(missing_ok=True)


@app.get("/api/progetti")
def elenco_progetti():
    elenco = []
    for c in sorted(PROGETTI.iterdir(), key=lambda p: p.stat().st_ctime, reverse=True):
        if c.is_dir() and not c.name.startswith("_") and (c / "richiesta.json").exists():
            d = _dettaglio(c)
            d.pop("analisi", None)
            elenco.append(d)
    return {"progetti": elenco}


@app.get("/api/progetti/{id_progetto}")
def dettaglio_progetto(id_progetto: str):
    cartella = _cartella(id_progetto)
    d = _dettaglio(cartella)
    if d["stato"].get("stato") == "errore" and (cartella / "errore.txt").exists():
        d["errore_dettaglio"] = (cartella / "errore.txt").read_text(encoding="utf-8")[-1500:]
    return d


@app.get("/api/progetti/{id_progetto}/file/{nome}")
def file_progetto(id_progetto: str, nome: str, scarica: int = 0):
    cartella = _cartella(id_progetto)
    percorso = (cartella / nome).resolve()
    if percorso.parent != cartella or not percorso.is_file():
        raise HTTPException(404, "File non trovato")
    if scarica:
        return FileResponse(percorso, filename=f"PrimaVista360_{id_progetto[:15]}_{nome}")
    return FileResponse(percorso, headers={"Cache-Control": "no-cache"})


@app.post("/api/progetti/{id_progetto}/apri-cartella")
def apri_cartella(id_progetto: str):
    cartella = _cartella(id_progetto)
    os.startfile(str(cartella))  # solo Windows: apre Esplora risorse
    return {"ok": True}


@app.post("/api/progetti/{id_progetto}/rifai")
def rifai(id_progetto: str):
    """Rilancia lo stesso lavoro (stessa foto, stessa richiesta) in un nuovo progetto."""
    vecchia = _cartella(id_progetto)
    r = _leggi_json(vecchia / "richiesta.json", {}) or {}
    foto = Path(r.get("foto", ""))
    if not foto.is_absolute():
        foto = RADICE / foto
    if not foto.exists():
        raise HTTPException(400, "Foto originale non trovata.")
    cartella = PROGETTI / pipeline.nome_cartella(r["richiesta"])
    cartella.mkdir(parents=True)
    copia = cartella / f"originale{foto.suffix.lower()}"
    shutil.copy2(foto, copia)
    modalita = r.get("modalita", "rinnova")
    (cartella / "richiesta.json").write_text(json.dumps(
        {"foto": str(copia), "nome_file": r.get("nome_file") or foto.name, "richiesta": r["richiesta"],
         "modalita": modalita, "servizio": r.get("servizio", "rinnova"),
         # da piantina resta da piantina; si tengono anche la casa e le piastrelle scelte
         **{k: r[k] for k in ("origine", "servizio_scelto", "stanza", "casa", "superfici") if k in r},
         "data": time.strftime("%d/%m/%Y %H:%M")}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    _prepara_rilievo(cartella, copia, _leggi_json(vecchia / "stanza_input.json"))
    return {"id": cartella.name}


def _elementi(cartella):
    if (cartella / "mappa_confermata.json").exists():
        return _leggi_json(cartella / "mappa_confermata.json", [])
    return (_leggi_json(cartella / "analisi.json", {}) or {}).get("elementi", [])


@app.get("/api/progetti/{id_progetto}/mappa")
def mappa(id_progetto: str):
    cartella = _cartella(id_progetto)
    analisi = _leggi_json(cartella / "analisi.json", {}) or {}
    return {"elementi": _elementi(cartella), "tipo_ambiente": analisi.get("tipo_ambiente", ""),
            "descrizione": analisi.get("descrizione_stanza", ""), "capitolato": analisi.get("capitolato_stile", "")}


@app.post("/api/progetti/{id_progetto}/mappa")
def aggiorna_mappa(id_progetto: str, dati: dict):
    """Cambia le categorie (id -> fisso/rinnova/togli) e ridisegna l'immagine della mappa."""
    cartella = _cartella(id_progetto)
    elementi = pipeline.conferma_mappa(cartella, dati.get("categorie", {}))
    return {"elementi": elementi}


@app.post("/api/progetti/{id_progetto}/conferma")
def conferma(id_progetto: str, dati: dict):
    cartella = _cartella(id_progetto)
    if _stato(cartella).get("stato") != "mappa_pronta":
        raise HTTPException(400, "Il progetto non è in attesa di conferma.")
    pipeline.conferma_mappa(cartella, dati.get("categorie", {}))
    _scrivi_stato(cartella, stato="in_corso", fase="ristrutturazione", testo="Avvio della ristrutturazione")
    _avvia(_lavora_genera, cartella)
    return {"ok": True}


@app.get("/api/versione")
def versione():
    """Data dell'ultima modifica della pagina: se cambia, il browser si ricarica da solo."""
    web = RADICE / "app" / "web"
    return {"versione": max(int(f.stat().st_mtime) for f in web.iterdir() if f.is_file())}


@app.get("/api/salute")
def salute():
    from dotenv import dotenv_values
    env = dotenv_values(RADICE / ".env")
    return JSONResponse({"openai": bool(env.get("OPENAI_API_KEY")), "anthropic": bool(env.get("ANTHROPIC_API_KEY")),
                         "spesa_massima": env.get("SPESA_MASSIMA_EURO", "5")})


# la pagina web (deve stare in fondo, dopo le API)
app.mount("/", StaticFiles(directory=RADICE / "app" / "web", html=True), name="web")
