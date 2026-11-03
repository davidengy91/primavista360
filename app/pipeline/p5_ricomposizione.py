"""
Passo 5 - Ricomposizione: rimette tutte le viste dentro un unico equirettangolare.

Due metodi:
- "sfumatura":  media pesata (ogni vista pesa 1 al centro e 0 ai bordi).
- "multibanda": come sopra ma separando dettagli fini e toni generali. I dettagli passano
                da una vista all'altra in una fascia stretta (niente immagini doppie),
                colori e luce si raccordano in una fascia larga (niente giunture visibili).
"""
import json
from pathlib import Path

import cv2
import numpy as np

from .geometria import proietta_vista_su_equi


def _sfumatura(viste_e_parametri, w_e, h_e, potenza_peso):
    somma = np.zeros((h_e, w_e, 3), np.float32)
    somma_pesi = np.zeros((h_e, w_e), np.float32)
    for img, v in viste_e_parametri:
        layer, peso = proietta_vista_su_equi(img, v["yaw"], v["pitch"], v["fov"], w_e, h_e,
                                             v.get("roll", 0.0), potenza_peso)
        somma += layer.astype(np.float32) * peso[..., None]
        somma_pesi += peso
    scoperti = somma_pesi <= 0
    risultato = somma / np.maximum(somma_pesi, 1e-8)[..., None]
    return risultato, scoperti


def _piramide(img, livelli):
    """Piramide gaussiana: l'immagine sempre più piccola e sfocata."""
    p = [img]
    for _ in range(livelli):
        p.append(cv2.pyrDown(p[-1]))
    return p


def _laplaciana(img, livelli):
    """Piramide laplaciana: l'immagine scomposta in 'bande' di dettaglio."""
    g = _piramide(img, livelli)
    lap = []
    for i in range(livelli):
        alto, largo = g[i].shape[:2]
        lap.append(g[i] - cv2.pyrUp(g[i + 1], dstsize=(largo, alto)))
    lap.append(g[-1])
    return lap


def _avvolgi(img, p):
    """Aggiunge p colonne a destra e sinistra prese dal lato opposto (il 360 si richiude)."""
    return np.concatenate([img[:, -p:], img, img[:, :p]], axis=1)


def ricomponi(viste_e_parametri, w_e, h_e, metodo="multibanda", livelli=5, potenza_peso=2.0):
    """viste_e_parametri: lista di (immagine BGR, dizionario con yaw/pitch/fov/roll).
    Restituisce (equirettangolare uint8, maschera dei pixel non coperti da nessuna vista)."""
    base, scoperti = _sfumatura(viste_e_parametri, w_e, h_e, potenza_peso)
    if metodo == "sfumatura":
        return np.clip(base + 0.5, 0, 255).astype(np.uint8), scoperti

    # Multibanda: ogni vista viene "completata" con la sfumatura fuori dalla sua area,
    # così le bande non hanno buchi neri che sporcherebbero i bordi.
    p = 2 ** livelli * 4
    somma_bande = None
    somma_pesi = None
    for img, v in viste_e_parametri:
        layer, peso = proietta_vista_su_equi(img, v["yaw"], v["pitch"], v["fov"], w_e, h_e,
                                             v.get("roll", 0.0), potenza_peso)
        completo = np.where((peso > 0)[..., None], layer.astype(np.float32), base)
        bande = _laplaciana(_avvolgi(completo, p), livelli)
        pesi = _piramide(_avvolgi(peso, p), livelli)
        if somma_bande is None:
            somma_bande = [b * w[..., None] for b, w in zip(bande, pesi)]
            somma_pesi = [w.copy() for w in pesi]
        else:
            for i in range(len(bande)):
                somma_bande[i] += bande[i] * pesi[i][..., None]
                somma_pesi[i] += pesi[i]
        del layer, peso, completo, bande, pesi

    # ricostruzione: dalla banda più grossolana a quella più fine
    risultato = somma_bande[-1] / np.maximum(somma_pesi[-1], 1e-8)[..., None]
    for i in range(livelli - 1, -1, -1):
        alto, largo = somma_bande[i].shape[:2]
        risultato = cv2.pyrUp(risultato, dstsize=(largo, alto)) + \
            somma_bande[i] / np.maximum(somma_pesi[i], 1e-8)[..., None]
    risultato = risultato[:, p:-p]
    risultato[scoperti] = base[scoperti]
    return np.clip(risultato + 0.5, 0, 255).astype(np.uint8), scoperti


def ricomponi_da_cartella(cartella, metodo="multibanda", livelli=5, potenza_peso=2.0, w_e=None, h_e=None):
    """Legge viste.json e le immagini della cartella e ricompone il 360.
    Se una vista è stata rigenerata a un'altra risoluzione va bene lo stesso."""
    cartella = Path(cartella)
    dati = json.loads((cartella / "viste.json").read_text(encoding="utf-8"))
    w_e = w_e or dati["larghezza_equi"]
    h_e = h_e or dati["altezza_equi"]
    viste = [(cv2.imread(str(cartella / v["file"]), cv2.IMREAD_COLOR), v) for v in dati["viste"]]
    return ricomponi(viste, w_e, h_e, metodo, livelli, potenza_peso)
