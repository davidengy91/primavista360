"""
Controllo geometrico automatico (senza AI, gratis): misura quanto la struttura della stanza
(muri, spigoli, finestre, porte) è rimasta nella stessa posizione dopo la ristrutturazione.

Come funziona: si trovano i "bordi lunghi" dell'originale (le linee della struttura, non i
dettagli piccoli come le piastrelle o gli oggetti) e si controlla quanti di questi hanno ancora
un bordo vicino (entro pochi pixel) nell'immagine nuova.
"""
import cv2
import numpy as np

LARGHEZZA_ANALISI = 2048


def _bordi(img, soglia_bassa=40, soglia_alta=120):
    grigio = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return cv2.Canny(cv2.GaussianBlur(grigio, (5, 5), 0), soglia_bassa, soglia_alta)


def _bordi_strutturali(img, lunghezza_minima=120):
    """Tiene solo i bordi lunghi (linee di muri, porte, finestre), scarta texture e oggetti piccoli."""
    bordi = _bordi(img, 60, 160)
    n, etichette, stat, _ = cv2.connectedComponentsWithStats(bordi, connectivity=8)
    lunghi = np.zeros_like(bordi)
    for i in range(1, n):
        w, h = stat[i, cv2.CC_STAT_WIDTH], stat[i, cv2.CC_STAT_HEIGHT]
        if max(w, h) >= lunghezza_minima:
            lunghi[etichette == i] = 255
    return lunghi


def punteggio_struttura(originale, generato, tolleranza_px=4):
    """Restituisce (punteggio 0-100, mappa colorata). 100 = struttura identica."""
    w = LARGHEZZA_ANALISI
    a = cv2.resize(originale, (w, w // 2), interpolation=cv2.INTER_AREA)
    b = cv2.resize(generato, (w, w // 2), interpolation=cv2.INTER_AREA)
    # si escludono i poli (righe molto stirate, poco affidabili)
    fascia = slice(int(w // 2 * 0.15), int(w // 2 * 0.85))
    struttura = _bordi_strutturali(a)[fascia]
    bordi_nuovi = _bordi(b)[fascia]
    distanza = cv2.distanceTransform(255 - bordi_nuovi, cv2.DIST_L2, 3)
    punti = struttura > 0
    if punti.sum() == 0:
        return 100.0, None
    ok = distanza[punti] <= tolleranza_px
    punteggio = 100.0 * ok.mean()
    # mappa: verde = struttura rispettata, rosso = struttura persa o spostata
    mappa = cv2.cvtColor(cv2.cvtColor(b[fascia], cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR) // 3
    yy, xx = np.nonzero(punti)
    colori = np.where(ok[:, None], [0, 255, 0], [0, 0, 255])
    for dy in (0, 1):
        mappa[np.clip(yy + dy, 0, mappa.shape[0] - 1), xx] = colori
    return punteggio, mappa
