"""
Modelli locali (gratis, sul PC, licenze libere anche per uso commerciale):

- Real-ESRGAN general x4 (BSD)    -> NITIDEZZA: porta il risultato da 3840 px alla risoluzione dell'originale.
"""
from pathlib import Path

import cv2
import numpy as np


RADICE = Path(__file__).resolve().parents[2]
TERZI = RADICE / "terzi"
_cache = {}


def disponibili():
    return {"esrgan": (TERZI / "esrgan" / "realesr-general-x4v3.pth").exists()}


# ------------------------------------------------------------------ NITIDEZZA (Real-ESRGAN)

def _esrgan():
    if "esrgan" not in _cache:
        import torch
        from spandrel import ModelLoader
        pesi = torch.load(str(TERZI / "esrgan" / "realesr-general-x4v3.pth"), map_location="cpu", weights_only=True)
        modello = ModelLoader().load_from_state_dict(pesi.get("params", pesi)).eval()
        _cache["esrgan"] = modello
    return _cache["esrgan"]


def aumenta_nitidezza(img_bgr, larghezza_finale, tassello=384, bordo=16):
    """Ingrandisce x4 a tasselli (per non finire la memoria) e riporta alla larghezza richiesta.
    Il 360 si richiude sui lati: si aggiunge un po' di bordo avvolto per non creare una cucitura."""
    import torch
    modello = _esrgan()
    h, w = img_bgr.shape[:2]
    # scala intermedia: basta arrivare poco sopra la larghezza finale
    fattore = 4
    avv = np.concatenate([img_bgr[:, -bordo:], img_bgr, img_bgr[:, :bordo]], axis=1)
    rgb = cv2.cvtColor(avv, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    H, W = rgb.shape[:2]
    uscita = np.zeros((H * fattore, W * fattore, 3), np.float32)
    with torch.no_grad():
        for y0 in range(0, H, tassello):
            for x0 in range(0, W, tassello):
                ya, xa = max(0, y0 - bordo), max(0, x0 - bordo)
                yb, xb = min(H, y0 + tassello + bordo), min(W, x0 + tassello + bordo)
                pezzo = torch.from_numpy(rgb[ya:yb, xa:xb].transpose(2, 0, 1)[None].copy())
                ris = modello(pezzo)[0].clamp(0, 1).numpy().transpose(1, 2, 0)
                # si tiene solo la parte centrale del tassello (i bordi servono di contesto)
                cy0, cx0 = (y0 - ya) * fattore, (x0 - xa) * fattore
                hh, ww = min(tassello, H - y0) * fattore, min(tassello, W - x0) * fattore
                uscita[y0 * fattore:y0 * fattore + hh, x0 * fattore:x0 * fattore + ww] = ris[cy0:cy0 + hh, cx0:cx0 + ww]
    uscita = uscita[:, bordo * fattore:-bordo * fattore]
    out = cv2.cvtColor((uscita * 255 + 0.5).clip(0, 255).astype(np.uint8), cv2.COLOR_RGB2BGR)
    return cv2.resize(out, (larghezza_finale, larghezza_finale // 2), interpolation=cv2.INTER_AREA)
