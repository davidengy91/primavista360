"""
Esperimento: far ristrutturare l'intero 360 equirettangolare in UNA sola chiamata.
Vantaggio atteso: una sola stanza coerente, niente doppioni tra viste.

Uso:  python test/prova_equirect_intero.py foto360.jpg cartella_progetto_con_analisi [larghezza] [qualita]
"""
import json
import sys
from pathlib import Path

import cv2
import numpy as np

RADICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RADICE))

from app.servizi.api import modifica_immagine  # noqa: E402
from app.servizi.costi import RegistroCosti  # noqa: E402

PROMPT = """This image is a full 360-degree EQUIRECTANGULAR panorama (2:1) of one real room, shot from a single point.
Renovate the room according to the specification below and return the SAME equirectangular panorama.

STRICT GEOMETRY RULES:
- Keep the exact equirectangular projection and the exact camera position: every wall edge, corner, ceiling line,
  window, door and French door must stay at the same pixel position. Straight lines stay curved exactly as now.
- The left and right borders of the image join each other (360 wrap): keep them continuous.
- The top row is the ceiling zenith and the bottom row is the floor nadir: keep them stretched as in a real panorama.
- Do not add, remove or move any opening. Elements that must not move: {fissi}.
- Corridors, passages, the entrance door and every door must stay IDENTICAL: same shape, same width,
  same depth and the same view through them. Do not invent new corridors, rooms or doors.
- Keep walls, pillars, curved walls, soffits, beams, radiators, air conditioner and sockets where they are.
  Only finishes, furniture, decor and lighting fixtures change.
- Remove the tripod at the bottom: continuous new floor there.

STYLE SPECIFICATION:
{capitolato}

Photorealistic high-end architectural interior photography, natural daylight from the real windows plus warm
3500-4000K light. No people, no text, no logos, no watermark."""


def main():
    foto, cartella = sys.argv[1], Path(sys.argv[2])
    larghezza = int(sys.argv[3]) if len(sys.argv) > 3 else 2048
    qualita = sys.argv[4] if len(sys.argv) > 4 else "medium"
    analisi = json.loads((cartella / "analisi.json").read_text(encoding="utf-8"))
    originale = cv2.imread(foto)
    equi = cv2.resize(originale, (larghezza, larghezza // 2), interpolation=cv2.INTER_AREA)
    registro = RegistroCosti(cartella / f"costi_equirect_{larghezza}.json", 1.0)
    prompt = PROMPT.format(fissi="; ".join(analisi["elementi_fissi"]), capitolato=analisi["capitolato_stile"])
    risultato = modifica_immagine([equi], prompt, None, "gpt-image-2.5-sunburst", None, qualita, registro,
                                  f"360 intero {larghezza}", dimensione=f"{larghezza}x{larghezza // 2}")
    risultato = cv2.resize(risultato, (larghezza, larghezza // 2), interpolation=cv2.INTER_LANCZOS4)
    cv2.imwrite(str(cartella / f"equirect_intero_{larghezza}.png"), risultato)
    # sovrapposizione dei bordi (rosso = originale, verde = generato) per vedere se la geometria regge
    def bordi(img):
        return cv2.Canny(cv2.GaussianBlur(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), (5, 5), 0), 50, 150)
    sovrapp = np.dstack([np.zeros_like(bordi(equi)), bordi(risultato), bordi(equi)])
    cv2.imwrite(str(cartella / f"equirect_intero_{larghezza}_bordi.png"), sovrapp)
    print("Costo:", registro.chiamate[-1])


if __name__ == "__main__":
    main()
