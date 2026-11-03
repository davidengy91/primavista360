"""
Passo 2 - Taglio: dal 360 equirettangolare estrae le viste prospettiche sovrapposte
(8 orizzontali ogni 45° + soffitto + pavimento) e salva i loro parametri in viste.json.
"""
import json
from pathlib import Path

import cv2

from .geometria import estrai_vista, lato_vista_consigliato


def schema_viste(larghezza_equi, viste_orizzontali=8, fov_orizzontali=100,
                 fov_zenit_nadir=110, sovracampionamento=1.0, lato_fisso=None):
    """Elenco delle viste da estrarre, con direzione e dimensione di ognuna.
    lato_fisso: se indicato, tutte le viste hanno quel lato in pixel (es. 1024 per l'AI)."""
    viste = []
    passo = 360 / viste_orizzontali
    lato = lato_fisso or lato_vista_consigliato(larghezza_equi, fov_orizzontali, sovracampionamento)
    for i in range(viste_orizzontali):
        viste.append({"nome": f"vista_{i + 1:02d}", "yaw": round(i * passo, 3), "pitch": 0.0,
                      "roll": 0.0, "fov": fov_orizzontali, "larghezza": lato, "altezza": lato})
    lato_poli = lato_fisso or lato_vista_consigliato(larghezza_equi, fov_zenit_nadir, sovracampionamento)
    viste.append({"nome": "zenit", "yaw": 0.0, "pitch": 90.0, "roll": 0.0,
                  "fov": fov_zenit_nadir, "larghezza": lato_poli, "altezza": lato_poli})
    viste.append({"nome": "nadir", "yaw": 0.0, "pitch": -90.0, "roll": 0.0,
                  "fov": fov_zenit_nadir, "larghezza": lato_poli, "altezza": lato_poli})
    return viste


def taglia(equi, cartella_uscita, impostazioni_taglio=None):
    """Estrae tutte le viste dall'immagine (array BGR) e le salva in PNG (senza perdita)
    nella cartella indicata, insieme a viste.json. Restituisce l'elenco delle viste."""
    cartella = Path(cartella_uscita)
    cartella.mkdir(parents=True, exist_ok=True)
    h, w = equi.shape[:2]
    viste = schema_viste(w, **(impostazioni_taglio or {}))
    for v in viste:
        img = estrai_vista(equi, v["yaw"], v["pitch"], v["fov"], v["larghezza"], v["altezza"], v["roll"])
        v["file"] = v["nome"] + ".png"
        cv2.imwrite(str(cartella / v["file"]), img)
    with open(cartella / "viste.json", "w", encoding="utf-8") as f:
        json.dump({"larghezza_equi": w, "altezza_equi": h, "viste": viste}, f, indent=2, ensure_ascii=False)
    return viste
