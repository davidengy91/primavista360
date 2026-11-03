"""
CATALOGO DELL'IMPRESA: i prodotti veri (sanitari, docce, vasche, mobili, rubinetteria…) da usare nei progetti.

Ogni prodotto ha nome, categoria, MISURE VERE (cm), dati commerciali e, se c'è, un modello 3D:
- caricato dall'impresa (GLB, GLTF, OBJ, FBX: i file dei produttori);
- oppure creato dalla FOTO del prodotto con Meshy (image-to-3D, consuma crediti Meshy).
Nel render il modello viene portato alle misure vere scritte nella scheda.
Senza modello 3D si usa una forma costruita a misura (come per i mobili generici).

Archivio: cartella catalogo/ con catalogo.json e una sottocartella per prodotto.
"""
import base64
import json
import os
import threading
import time
import traceback
import urllib.request
from pathlib import Path

RADICE = Path(__file__).resolve().parents[1]
try:
    from dotenv import load_dotenv
    load_dotenv(RADICE / ".env")                     # MESHY_API_KEY sta nel .env, mai nel codice
except ImportError:
    pass
CARTELLA = RADICE / "catalogo"
INDICE = CARTELLA / "catalogo.json"
MESHY = "https://api.meshy.ai/openapi/v1/image-to-3d"
FORMATI_MODELLO = (".glb", ".gltf", ".obj", ".fbx")
FORMATI_FOTO = (".jpg", ".jpeg", ".png", ".webp")
POSE = ["dritta", "sfalsata", "terzo", "diagonale"]
FINITURE = ["opaca", "satinata", "lucida", "strutturata"]      # la prima è quella proposta: lucida solo se scelta
TIPI_LUCE = ["faretto", "plafoniera", "sospensione", "applique"]
CATEGORIE = ["Piastrella", "Sanitari", "Doccia", "Vasca", "Mobile bagno", "Specchio", "Rubinetteria", "Termoarredo",
             "Cucina", "Letto", "Divano", "Tavolo", "Sedia", "Armadio", "Arredo", "Illuminazione", "Altro"]
_blocco = threading.Lock()


def _leggi():
    if not INDICE.exists():
        return []
    return json.loads(INDICE.read_text(encoding="utf-8"))


def _scrivi(prodotti):
    CARTELLA.mkdir(exist_ok=True)
    INDICE.write_text(json.dumps(prodotti, ensure_ascii=False, indent=2), encoding="utf-8")


def _proporzioni_glb(percorso):
    """Ingombro del modello GLB/GLTF (larghezza, profondità, altezza nelle sue unità), letto dal file senza Blender:
    min/max delle posizioni (glTF ha l'alto su Y). None se non si riesce."""
    import struct
    try:
        dati = Path(percorso).read_bytes()
        if dati[:4] == b"glTF":
            lung = struct.unpack("<I", dati[12:16])[0]
            gltf = json.loads(dati[20:20 + lung])
        else:
            gltf = json.loads(dati.decode("utf-8"))
        mn, mx = [1e9] * 3, [-1e9] * 3
        for mesh in gltf.get("meshes", []):
            for prim in mesh.get("primitives", []):
                acc = gltf["accessors"][prim["attributes"]["POSITION"]]
                for i in range(3):
                    mn[i] = min(mn[i], acc["min"][i]); mx[i] = max(mx[i], acc["max"][i])
        d = [mx[i] - mn[i] for i in range(3)]
        return [round(d[0], 4), round(d[2], 4), round(d[1], 4)] if min(d) > 0 else None
    except Exception:  # noqa: BLE001
        return None


def elenco():
    """Elenco dei prodotti. Per i modelli 3D pronti calcola una volta le proporzioni (servono all'avviso
    "larghezza e profondità invertite?" nella scheda)."""
    prodotti = _leggi()
    for p in prodotti:
        if p.get("stato_modello") == "pronto" and p.get("modello", "").lower().endswith((".glb", ".gltf"))                 and p.get("proporzioni_modello") is None:
            prop = _proporzioni_glb(CARTELLA / p["id"] / p["modello"])
            _aggiorna(p["id"], proporzioni_modello=prop or [])
            p["proporzioni_modello"] = prop or []
    return prodotti


def prodotto(pid):
    return next((p for p in _leggi() if p["id"] == pid), None)


def percorso_modello(pid):
    """Percorso assoluto del modello 3D del prodotto, se pronto (per il render)."""
    p = prodotto(pid)
    if p and p.get("modello") and p.get("stato_modello") == "pronto":
        f = CARTELLA / pid / p["modello"]
        return str(f) if f.exists() else None
    return None


def _aggiorna(pid, **campi):
    with _blocco:
        prodotti = _leggi()
        for p in prodotti:
            if p["id"] == pid:
                p.update(campi)
        _scrivi(prodotti)


def aggiungi(dati, foto=None, modello=None):
    """dati: nome, categoria, larghezza, profondita, altezza, quota, fornitore, codice, prezzo, nota, rotazione_modello.
    foto / modello: (nome_file, bytes) facoltativi."""
    pid = f"p{int(time.time() * 1000)}"
    cartella = CARTELLA / pid
    cartella.mkdir(parents=True, exist_ok=True)
    tipo = "piastrella" if dati.get("tipo") == "piastrella" else "prodotto"
    p = {"id": pid, "tipo": tipo, "nome": dati["nome"].strip(),
         "categoria": "Piastrella" if tipo == "piastrella" else (dati.get("categoria") or "Altro"),
         # piastrella: larghezza x profondita = FORMATO (es. 60 x 120), altezza = spessore
         # foto_tipo: "piastrella" = la foto è UNA piastrella (larghezza x profondita = formato);
         # "superficie" = la foto è un pezzo di pavimento già posato (larghezza x profondita = quanto copre la foto)
         "foto_tipo": "superficie" if dati.get("foto_tipo") == "superficie" else "piastrella",
         "finitura": dati.get("finitura") or "opaca", "fuga_colore": dati.get("fuga_colore") or "#b9b2a6",
         "fuga_mm": int(dati.get("fuga_mm") or 2), "posa": dati.get("posa") or "dritta",
         "larghezza": int(dati["larghezza"]), "profondita": int(dati["profondita"]), "altezza": int(dati["altezza"]),
         "quota": int(dati.get("quota") or 0), "fornitore": dati.get("fornitore", ""), "codice": dati.get("codice", ""),
         "prezzo": dati.get("prezzo", ""), "nota": dati.get("nota", ""),
         "rotazione_modello": int(dati.get("rotazione_modello") or 0),
         # luci: tipo (faretto, plafoniera, sospensione, applique), temperatura in Kelvin, calata per le sospensioni (cm)
         "tipo_luce": dati.get("tipo_luce") if dati.get("tipo_luce") in TIPI_LUCE else "faretto",
         "k": int(dati.get("k") or 3000), "calata": int(dati.get("calata") or 70),
         # specchi: retroilluminato con LED
         "led": str(dati.get("led", "")).lower() in ("1", "true", "on", "si", "sì"),
         "luce_specchio": dati.get("luce_specchio") if dati.get("luce_specchio") in ("sopra", "dietro") else "",
         # "proporzioni" = il modello si ingrandisce in proporzione dalla larghezza; "esatte" = stirato sulle 3 misure
         "scala_modello": "esatte" if dati.get("scala_modello") == "esatte" else "proporzioni",
         "foto": None, "modello": None, "anteprima": None, "stato_modello": "nessuno", "messaggio": "",
         "data": time.strftime("%d/%m/%Y")}
    if foto:
        est = Path(foto[0]).suffix.lower()
        if est not in FORMATI_FOTO:
            raise ValueError("La foto deve essere JPG, PNG o WEBP.")
        (cartella / f"foto{est}").write_bytes(foto[1])
        p["foto"] = p["anteprima"] = f"foto{est}"
    if modello and tipo == "prodotto":
        _salva_modello(p, cartella, modello)
    if tipo == "piastrella" and not foto:
        import shutil
        shutil.rmtree(cartella, ignore_errors=True)
        raise ValueError("Per una piastrella serve la foto della superficie (dritta, senza ombre).")
    with _blocco:
        prodotti = _leggi()
        prodotti.insert(0, p)
        _scrivi(prodotti)
    return p


def _salva_modello(p, cartella, modello):
    est = Path(modello[0]).suffix.lower()
    if est not in FORMATI_MODELLO:
        raise ValueError("Il modello 3D deve essere GLB, GLTF, OBJ o FBX.")
    (cartella / f"modello{est}").write_bytes(modello[1])
    p.update({"modello": f"modello{est}", "stato_modello": "pronto", "messaggio": "Modello caricato", "proporzioni_modello": None})


def carica_modello(pid, modello):
    p = prodotto(pid)
    if not p:
        raise KeyError(pid)
    _salva_modello(p, CARTELLA / pid, modello)
    _aggiorna(pid, modello=p["modello"], stato_modello="pronto", messaggio="Modello caricato", proporzioni_modello=None)


def modifica(pid, campi):
    ammessi = {"nome", "categoria", "larghezza", "profondita", "altezza", "quota", "fornitore", "codice", "prezzo",
               "nota", "rotazione_modello", "finitura", "fuga_colore", "fuga_mm", "posa", "scala_modello",
               "foto_tipo", "tipo_luce", "k", "calata", "led", "luce_specchio"}
    if "led" in campi:
        campi["led"] = str(campi["led"]).lower() in ("1", "true", "on", "si", "sì")
    for k in ("larghezza", "profondita", "altezza", "quota", "fuga_mm", "rotazione_modello", "k", "calata"):
        if k in campi:
            campi[k] = int(float(campi[k] or 0))
    if "nome" in campi and not str(campi["nome"]).strip():
        raise ValueError("Il nome non può essere vuoto.")
    _aggiorna(pid, **{k: v for k, v in campi.items() if k in ammessi})


def togli(pid):
    import shutil
    with _blocco:
        _scrivi([p for p in _leggi() if p["id"] != pid])
    shutil.rmtree(CARTELLA / pid, ignore_errors=True)


# ------------------------------------------------------------------ Meshy: modello 3D dalla foto

def meshy_disponibile():
    return bool(os.getenv("MESHY_API_KEY"))


def _richiesta(url, dati=None):
    intestazioni = {"Authorization": f"Bearer {os.getenv('MESHY_API_KEY')}"}
    corpo = None
    if dati is not None:
        corpo = json.dumps(dati).encode()
        intestazioni["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=corpo, headers=intestazioni, method="POST" if dati is not None else "GET")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


def _scarica(url, destinazione):
    with urllib.request.urlopen(url, timeout=300) as r:
        destinazione.write_bytes(r.read())


def crea_da_foto(pid):
    """Avvia la creazione del modello 3D dalla foto (in background). Il prodotto passa a 'in_creazione'."""
    p = prodotto(pid)
    if not p or not p.get("foto"):
        raise ValueError("Serve prima la foto del prodotto.")
    if not meshy_disponibile():
        raise ValueError("Manca la chiave di Meshy: aggiungi MESHY_API_KEY nel file .env e riavvia il programma.")
    _aggiorna(pid, stato_modello="in_creazione", messaggio="Meshy sta creando il modello 3D (1-3 minuti)", avanzamento=0)
    threading.Thread(target=_lavora_meshy, args=(pid,), daemon=True).start()


def _lavora_meshy(pid):
    cartella = CARTELLA / pid
    try:
        p = prodotto(pid)
        foto = cartella / p["foto"]
        tipo = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png", "webp": "webp"}[foto.suffix.lower().lstrip(".")]
        uri = f"data:image/{tipo};base64," + base64.b64encode(foto.read_bytes()).decode()
        compito = _richiesta(MESHY, {"image_url": uri, "should_texture": True, "enable_pbr": True,
                                     "should_remesh": True, "target_polycount": 60000, "target_formats": ["glb"]})["result"]
        _aggiorna(pid, meshy_task=compito)
        inizio = time.time()
        while True:
            time.sleep(6)
            stato = _richiesta(f"{MESHY}/{compito}")
            _aggiorna(pid, avanzamento=stato.get("progress", 0))
            if stato["status"] == "SUCCEEDED":
                _scarica(stato["model_urls"]["glb"], cartella / "modello.glb")
                if stato.get("thumbnail_url"):
                    _scarica(stato["thumbnail_url"], cartella / "anteprima_3d.png")
                _aggiorna(pid, modello="modello.glb", proporzioni_modello=None, anteprima="anteprima_3d.png" if (cartella / "anteprima_3d.png").exists()
                          else p.get("anteprima"), stato_modello="pronto",
                          messaggio=f"Modello 3D creato da Meshy ({stato.get('consumed_credits', '?')} crediti)")
                return
            if stato["status"] in ("FAILED", "CANCELED"):
                errore = (stato.get("task_error") or {}).get("message", stato["status"])
                _aggiorna(pid, stato_modello="errore", messaggio=f"Meshy non è riuscito: {errore}")
                return
            if time.time() - inizio > 900:
                _aggiorna(pid, stato_modello="errore", messaggio="Meshy non ha risposto entro 15 minuti")
                return
    except Exception as e:  # noqa: BLE001
        (cartella / "errore_meshy.txt").write_text(traceback.format_exc(), encoding="utf-8")
        _aggiorna(pid, stato_modello="errore", messaggio=f"Errore con Meshy: {e}")


def percorso_foto(pid):
    """Foto della piastrella (la superficie): diventa il materiale nel render, in scala reale."""
    p = prodotto(pid)
    if p and p.get("foto"):
        f = CARTELLA / pid / p["foto"]
        return str(f) if f.exists() else None
    return None
