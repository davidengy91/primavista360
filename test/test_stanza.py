"""
Prova della ricostruzione della stanza SENZA AI:
1. si inventa una stanza vera (misure note, ruotata, camera fuori centro) con porta, finestra e mobili;
2. si calcolano gli angoli come li cliccherebbe il fotografo (yaw/pitch, con un piccolo errore di mira);
3. si ricostruisce la stanza e si confrontano le misure con quelle vere;
4. si disegnano guida pulita, guida di controllo e pianta.

Uso:  python test/test_stanza.py
"""
import math
import sys
import time
from pathlib import Path

import cv2
import numpy as np

RADICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RADICE))

from app.pipeline.p3_guida import guida_controllo, guida_pulita, pianta  # noqa: E402
from app.pipeline.p3_stanza import PRESET_MOBILI, costruisci  # noqa: E402


def yaw_pitch(x, y, z, theta):
    """Da coordinate stanza a yaw/pitch del viewer."""
    c, s = math.cos(theta), math.sin(theta)
    wx, wz = c * x - s * z, s * x + c * z
    return [math.degrees(math.atan2(wx, wz)), math.degrees(math.atan2(y, math.hypot(wx, wz)))]


def main():
    cartella = RADICE / "progetti" / "_test_stanza"
    cartella.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(1)
    vera = {"XL": -1.7, "XR": 2.3, "ZB": -1.6, "ZW": 2.9, "H": 2.75, "theta": math.radians(17), "h": 1.5}
    errore_mira = 0.3   # gradi: un clic un po' impreciso
    angoli = [yaw_pitch(x, -vera["h"], z, vera["theta"])
              for x, z in ((vera["XL"], vera["ZB"]), (vera["XR"], vera["ZB"]), (vera["XR"], vera["ZW"]),
                           (vera["XL"], vera["ZW"]))]
    angoli = [[a + rng.normal(0, errore_mira), b + rng.normal(0, errore_mira)] for a, b in angoli]
    soffitto = yaw_pitch(vera["XR"], vera["H"] - vera["h"], vera["ZW"], vera["theta"])
    porta = [yaw_pitch(-0.2, -vera["h"] + 2.1, vera["ZW"], vera["theta"]),
             yaw_pitch(0.7, -vera["h"], vera["ZW"], vera["theta"])]
    finestra = [yaw_pitch(vera["XR"], -vera["h"] + 2.2, 0.2, vera["theta"]),
                yaw_pitch(vera["XR"], -vera["h"] + 0.9, 1.4, vera["theta"])]
    dati = {
        "altezza_camera": 1.5, "angoli": angoli, "soffitto": soffitto,
        "fissi": [{"tipo": "porta", "nome": "Porta", "p1": porta[0], "p2": porta[1]},
                  {"tipo": "finestra", "nome": "Finestra", "p1": finestra[0], "p2": finestra[1]}],
        "mobili": [
            {"nome": "Divano", **PRESET_MOBILI["Divano"], "centro": [-0.5, -1.0]},
            {"nome": "Tavolo", **PRESET_MOBILI["Tavolo tondo"], "centro": [1.0, 1.6]},
            {"nome": "Tappeto", **PRESET_MOBILI["Tappeto"], "centro": [-0.4, 0.2], "rotazione": 90},
            {"nome": "Libreria", **PRESET_MOBILI["Libreria"], "centro": [-1.6, 1.8]},
        ],
    }
    t = time.time()
    s = costruisci(dati)
    print("Misure vere:      larghezza %.2f  profondità %.2f  altezza %.2f" %
          (vera["XR"] - vera["XL"], vera["ZW"] - vera["ZB"], vera["H"]))
    m = s["misure"]
    print("Misure ricostruite: larghezza %.2f  profondità %.2f  altezza %.2f  (scarto angoli %.1f cm)" %
          (m["larghezza_m"], m["profondita_m"], m["altezza_m"], m["scarto_angoli_cm"]))
    print("Rotazione vera %.1f°, ricostruita %.1f°" % (math.degrees(vera["theta"]), math.degrees(s["theta"])))
    print("Elementi fissi:", [(f["nome"], f["parete"], [round(x, 2) for x in f["u"]], [round(x, 2) for x in f["v"]])
                              for f in s["fissi"]])
    print("Avvisi:", s["avvisi"])

    pulita, rc = guida_pulita(s, 2048)
    controllo, _ = guida_controllo(s, pulita, 2048, rc=rc)
    cv2.imwrite(str(cartella / "guida_pulita.jpg"), pulita)
    cv2.imwrite(str(cartella / "guida_controllo.jpg"), controllo)
    cv2.imwrite(str(cartella / "pianta.png"), pianta(s))
    print(f"Disegni in {time.time() - t:.1f} s -> {cartella}")


if __name__ == "__main__":
    main()
