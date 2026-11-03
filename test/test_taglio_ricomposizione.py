"""
Prova senza AI: taglio -> ricomposizione -> confronto con l'originale.
Se il risultato è (quasi) identico, la base geometrica è giusta.

Uso:
    python test/test_taglio_ricomposizione.py                 (usa un 360 sintetico di prova)
    python test/test_taglio_ricomposizione.py percorso.jpg    (usa un tuo 360)
"""
import sys
import time
from pathlib import Path

import cv2
import numpy as np

RADICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RADICE))

from app.pipeline.p2_taglio import taglia  # noqa: E402
from app.pipeline.p5_ricomposizione import ricomponi_da_cartella  # noqa: E402
from app.pipeline.p7_output import leggi_gpano, salva_jpg_360  # noqa: E402


def crea_360_sintetico(larghezza=7680):
    """Un 360 finto ma 'difficile': griglia, scritte, texture fine e sfumature."""
    altezza = larghezza // 2
    rng = np.random.default_rng(0)
    img = cv2.resize(rng.integers(0, 255, (altezza // 16, larghezza // 16, 3), dtype=np.uint8),
                     (larghezza, altezza), interpolation=cv2.INTER_CUBIC)
    rumore = cv2.GaussianBlur(rng.normal(0, 18, (altezza, larghezza, 3)).astype(np.float32), (0, 0), 1.2)
    # come in una foto vera, verso i poli il dettaglio orizzontale è 'stirato'
    fasce = 36
    for k in range(fasce):
        y0, y1 = k * altezza // fasce, (k + 1) * altezza // fasce
        lat = (0.5 - (y0 + y1) / 2 / altezza) * np.pi
        sigma = min(1.0 / max(np.cos(lat), 1e-3), 200)
        rumore[y0:y1] = cv2.GaussianBlur(rumore[y0:y1], (0, 0), sigmaX=sigma, sigmaY=0.01)
    img = np.clip(img.astype(np.float32) + rumore, 0, 255).astype(np.uint8)
    for x in range(0, larghezza, larghezza // 36):          # meridiani ogni 10°
        cv2.line(img, (x, 0), (x, altezza), (255, 255, 255), 3)
    for y in range(0, altezza, altezza // 18):              # paralleli ogni 10°
        cv2.line(img, (0, y), (larghezza, y), (0, 0, 0), 3)
    for i in range(36):
        cv2.putText(img, f"{i * 10}", (i * larghezza // 36 + 20, altezza // 2 - 20),
                    cv2.FONT_HERSHEY_SIMPLEX, larghezza / 2500, (0, 255, 255), 4, cv2.LINE_AA)
    return img


def _psnr(mse):
    return 10 * np.log10(255 ** 2 / mse) if mse > 0 else float("inf")


def misura(originale, ricomposto):
    """Confronto pixel per pixel. Nel 360 le righe vicino ai poli sono 'stirate' (migliaia di
    pixel per un cerchietto minuscolo), quindi si usa anche il WS-PSNR, la misura standard
    per i 360: pesa ogni pixel per l'area reale di sfera che rappresenta."""
    diff = np.abs(originale.astype(np.float32) - ricomposto.astype(np.float32))
    h = diff.shape[0]
    lat = (0.5 - (np.arange(h) + 0.5) / h) * np.pi
    peso_righe = np.cos(lat)[:, None, None]
    mse_sfera = float((diff ** 2 * peso_righe).sum() / (peso_righe.sum() * diff.shape[1] * 3))
    fascia = np.abs(lat) < np.radians(60)      # pareti: da -60° a +60°
    return {"errore_medio": float(diff.mean()),
            "errore_99pct": float(np.percentile(diff, 99)),
            "psnr_db": _psnr(float(np.mean(diff ** 2))),
            "ws_psnr_db": _psnr(mse_sfera),
            "psnr_pareti_db": _psnr(float(np.mean(diff[fascia] ** 2)))}, diff.max(axis=2)


def main():
    cartella = RADICE / "progetti" / "_test_geometria"
    cartella.mkdir(parents=True, exist_ok=True)
    if len(sys.argv) > 1:
        sorgente = sys.argv[1]
        originale = cv2.imread(sorgente, cv2.IMREAD_COLOR)
        print("Metadati 360 dell'originale:", leggi_gpano(sorgente) or "NESSUNO")
    else:
        sorgente = None
        originale = crea_360_sintetico()
        cv2.imwrite(str(cartella / "originale_sintetico.png"), originale)
    h, w = originale.shape[:2]
    print(f"Immagine: {w} x {h} (rapporto {w / h:.3f})")

    t = time.time()
    viste = taglia(originale, cartella / "viste")
    print(f"Taglio: {len(viste)} viste in {time.time() - t:.1f} s "
          f"(lato {viste[0]['larghezza']} px orizzontali, {viste[-1]['larghezza']} px poli)")

    for metodo in ("sfumatura", "multibanda"):
        t = time.time()
        ricomposto, scoperti = ricomponi_da_cartella(cartella / "viste", metodo=metodo)
        durata = time.time() - t
        risultati, mappa = misura(originale, ricomposto)
        print(f"\n[{metodo}] ricomposizione in {durata:.1f} s")
        print(f"  pixel non coperti da nessuna vista: {int(scoperti.sum())}")
        print(f"  errore medio: {risultati['errore_medio']:.2f} / 255")
        print(f"  errore al 99° percentile: {risultati['errore_99pct']:.1f} / 255")
        print(f"  PSNR semplice: {risultati['psnr_db']:.1f} dB")
        print(f"  WS-PSNR (misura standard 360): {risultati['ws_psnr_db']:.1f} dB")
        print(f"  PSNR solo pareti (-60°..+60°): {risultati['psnr_pareti_db']:.1f} dB")
        print("  (sopra ~35 dB la differenza non si vede a occhio)")
        cv2.imwrite(str(cartella / f"differenza_x10_{metodo}.png"), np.clip(mappa * 10, 0, 255).astype(np.uint8))
        salva_jpg_360(ricomposto, str(cartella / f"ricomposto_{metodo}.jpg"), originale=sorgente)

    print("\nMetadati 360 scritti nel JPG:", leggi_gpano(str(cartella / "ricomposto_multibanda.jpg")))


if __name__ == "__main__":
    main()
