"""
Ponte tra il programma e Blender: prepara la scena (misure, fissi, mobili, finiture) e lancia il render 360.

Il render gira in un processo Blender separato, senza finestra: il programma resta libero.
"""
import json
import logging
import subprocess
import time
from pathlib import Path

log = logging.getLogger(__name__)

QUI = Path(__file__).resolve().parent
SCRIPT = QUI / "scena_blender.py"
BLENDER = [
    Path("C:/Program Files/Blender Foundation/Blender 5.2/blender.exe"),
    Path("C:/Program Files/Blender Foundation/Blender 4.5/blender.exe"),
]


def trova_blender():
    for p in BLENDER:
        if p.exists():
            return p
    raise RuntimeError("Blender non trovato: installalo (5.2) per il motore 3D.")


# ------------------------------------------------------------------ finiture dallo stile scritto dal cliente

PALETTE = {
    # parola nella richiesta -> finiture (colori sRGB, formati in metri)
    "marmo": {"pavimento": {"tipo": "gres", "colore1": "#ece9e4", "colore2": "#e2ded8", "fuga": "#d8d4cd", "largo": 0.6, "alto": 1.2, "ruvidita": 0.12}},
    "rovere": {"pavimento": {"tipo": "parquet", "chiaro": "#c9a77f", "scuro": "#a17d55", "largo": 1.2, "alto": 0.18}},
    "parquet": {"pavimento": {"tipo": "parquet", "chiaro": "#c9a77f", "scuro": "#a17d55", "largo": 1.2, "alto": 0.18}},
    "noce": {"legno_mobili": {"chiaro": "#7a5537", "scuro": "#5a3c25"}},
    "tortora": {"pareti": {"colore": "#cfc6b8"}},
    "grigio": {"pareti": {"colore": "#d6d6d3"}},
    "nero": {"accento": "#151515"},
    "ottone": {"accento": "#b08d57"},
    "cromo": {"accento": "#c9ccd0"},
    "luxury": {"accento": "#b08d57"},
}


def finiture(richiesta, bagno):
    """Finiture di base (eleganti e neutre) corrette dalle parole dello stile. Il bagno ha il rivestimento."""
    f = {
        "pavimento": {"tipo": "gres", "colore1": "#cfc8bd", "colore2": "#c8c0b4", "fuga": "#bab3a8", "largo": 0.6, "alto": 0.6, "ruvidita": 0.3},
        "pareti": {"colore": "#e2ddd4"},
        "accento": "#2b2b2b",
    }
    if bagno:
        f["pavimento"] = {"tipo": "gres", "colore1": "#a99f92", "colore2": "#a2988b", "fuga": "#8c8378", "largo": 0.6, "alto": 1.2, "ruvidita": 0.25}
        f["rivestimento"] = {"colore1": "#e3ded5", "colore2": "#ddd7cd", "fuga": "#b9b2a6", "largo": 0.6, "alto": 0.3,
                             "altezza": 1.2, "ruvidita": 0.1}
    testo = (richiesta or "").lower()
    for parola, valori in PALETTE.items():
        if parola in testo:
            for k, v in valori.items():
                if k == "pavimento" and bagno and v.get("tipo") == "parquet":
                    continue            # niente parquet in bagno
                f[k] = v
    if bagno and ("tutta altezza" in testo or "fino al soffitto" in testo):
        f["rivestimento"]["altezza"] = 3.0
    return f


def _con_modello(m):
    """Mobile dal catalogo dell'impresa: se ha un modello 3D pronto, Blender usa quello (portato alle misure vere)."""
    if m.get("catalogo"):
        from .. import catalogo
        p = catalogo.prodotto(m["catalogo"])
        percorso = catalogo.percorso_modello(m["catalogo"])
        if percorso:
            m["modello"] = percorso
            m["rotazione_modello"] = (p or {}).get("rotazione_modello", 0)
        if p and p.get("categoria") == "Illuminazione":
            m["luce"], m["k"] = True, p.get("k", 3000)          # applique del catalogo: si accende
        if p and p.get("categoria") == "Specchio":
            m["led"] = m.get("led") or p.get("led", False)
            m["luce_specchio"] = p.get("luce_specchio") or ("dietro" if p.get("led") else "")
            m["scala_modello"] = (p or {}).get("scala_modello", "proporzioni")
    return m


ZONE = ["pavimento", "pareti", "parete_fondo", "parete_destra", "parete_dietro", "parete_sinistra",
        "rivestimento", "zona_lavabo", "zona_vasca", "doccia", "soffitto"]


def superfici_per_blender(superfici):
    """Zone scelte nel progetto ({zona: {piastrella: id catalogo | colore, altezza, posa}}) -> dati per Blender,
    con il percorso della foto e il formato in metri. Le piastrelle sparite dal catalogo si saltano."""
    from .. import catalogo
    out = {}
    for zona, spec in (superfici or {}).items():
        if zona not in ZONE or not spec:
            continue
        z = {k: spec[k] for k in ("colore", "altezza", "verso") if spec.get(k) not in (None, "")}
        if z.get("altezza") is not None:
            z["altezza"] = float(z["altezza"]) / 100          # dal programma arriva in cm
        if spec.get("piastrella"):
            p = catalogo.prodotto(spec["piastrella"])
            foto = catalogo.percorso_foto(spec["piastrella"])
            if not p or not foto:
                continue
            z["piastrella"] = {"foto": foto, "largo": p["larghezza"] / 100, "alto": p["profondita"] / 100,
                               "fuga_mm": p.get("fuga_mm", 2), "fuga_colore": p.get("fuga_colore", "#b9b2a6"),
                               "finitura": p.get("finitura", "opaca"), "posa": spec.get("posa") or p.get("posa", "dritta"),
                               "foto_tipo": p.get("foto_tipo", "piastrella")}
        if z.get("piastrella") or z.get("colore"):
            out[zona] = z
    return out


def _luce_catalogo(l):
    """Luce a soffitto presa dal catalogo: tipo, temperatura, calata, misure e modello 3D veri."""
    if l.get("catalogo"):
        from .. import catalogo
        p = catalogo.prodotto(l["catalogo"])
        if p:
            l.update({"tipo": p.get("tipo_luce", l.get("tipo", "faretto")), "k": p.get("k", l.get("k", 3000)),
                      "calata": p.get("calata", 70), "L": p["larghezza"] / 100, "P": p["profondita"] / 100,
                      "A": p["altezza"] / 100, "rotazione_modello": p.get("rotazione_modello", 0),
                      "scala_modello": p.get("scala_modello", "proporzioni")})
            percorso = catalogo.percorso_modello(l["catalogo"])
            if percorso:
                l["modello"] = percorso
    return l


def prepara(s, richiesta="", superfici=None):
    """Dalla stanza calcolata (p3_stanza.costruisci, già serializzata) ai dati per Blender."""
    nomi = " ".join(f"{m.get('nome', '')} {m.get('tipo', '')}".lower() for m in s.get("mobili", []))
    bagno = any(k in nomi for k in ("wc", "bidet", "doccia", "vasca", "lavabo", "mobile bagno")) or "bagno" in (richiesta or "").lower()
    return {
        "stanza": {k: s[k] for k in ("XL", "XR", "ZB", "ZW", "H", "h", "theta")},
        "fissi": [{k: f[k] for k in ("tipo", "parete", "u", "v")} for f in s.get("fissi", [])],
        "mobili": [_con_modello({k: m.get(k) for k in ("nome", "tipo", "centro_m", "L", "P", "A", "rot", "quota_m", "forma",
                                                       "catalogo", "led", "luce_specchio")})
                   for m in s.get("mobili", []) if m.get("centro_m")],
        "finiture": finiture(richiesta, bagno),
        "superfici": superfici_per_blender(superfici),
        "luci": [_luce_catalogo(dict(l)) for l in s.get("luci", [])],
        "atmosfera": s.get("atmosfera", "giorno"),
    }


def render(scena, uscita, larghezza=4096, campioni=128, esposizione=-0.6, timeout=1800):
    """Lancia Blender senza finestra. Restituisce i secondi impiegati. Solleva un errore leggibile se fallisce."""
    uscita = Path(uscita).resolve()
    scena = {**scena, "render": {"larghezza": larghezza, "campioni": campioni, "esposizione": esposizione}}
    file_scena = uscita.with_suffix(".scena.json")
    file_scena.write_text(json.dumps(scena, ensure_ascii=False, indent=2), encoding="utf-8")
    comando = [str(trova_blender()), "-b", "--factory-startup", "-P", str(SCRIPT), "--", str(file_scena), str(uscita)]
    t0 = time.time()
    r = subprocess.run(comando, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    secondi = time.time() - t0
    (uscita.with_suffix(".log.txt")).write_text(r.stdout[-20000:] + "\n--- errori ---\n" + r.stderr[-8000:], encoding="utf-8")
    if r.returncode != 0 or not uscita.exists():
        righe = [x for x in (r.stdout + r.stderr).splitlines() if "Error" in x or "Traceback" in x or "rror:" in x]
        raise RuntimeError("Render Blender non riuscito: " + (" | ".join(righe[-3:]) or f"codice {r.returncode}"))
    log.info("Render Blender %s in %.0f s", uscita.name, secondi)
    return secondi
