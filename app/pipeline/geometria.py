"""
Matematica delle proiezioni: equirettangolare <-> vista prospettica.

Convenzioni (valgono per tutto il programma):
- yaw   = rotazione orizzontale in gradi. 0 = centro della foto 360, positivo = verso destra.
- pitch = inclinazione in gradi. 0 = orizzonte, +90 = soffitto (zenit), -90 = pavimento (nadir).
- roll  = rotazione attorno all'asse di vista (di solito 0).
- fov   = campo visivo ORIZZONTALE della vista, in gradi.

Nello spazio 3D: x = destra, y = alto, z = avanti.
"""
import numpy as np
import cv2


def matrice_rotazione(yaw, pitch, roll=0.0):
    """Restituisce la matrice che porta una direzione dalla 'fotocamera virtuale' al mondo."""
    y, p, r = np.radians([yaw, pitch, roll])
    # pitch: rotazione attorno all'asse x (guarda in alto/basso)
    rx = np.array([[1, 0, 0],
                   [0, np.cos(p), np.sin(p)],
                   [0, -np.sin(p), np.cos(p)]])
    # yaw: rotazione attorno all'asse y (gira a destra/sinistra)
    ry = np.array([[np.cos(y), 0, np.sin(y)],
                   [0, 1, 0],
                   [-np.sin(y), 0, np.cos(y)]])
    # roll: rotazione attorno all'asse z
    rz = np.array([[np.cos(r), -np.sin(r), 0],
                   [np.sin(r), np.cos(r), 0],
                   [0, 0, 1]])
    return ry @ rx @ rz


def _bordo_equi(equi, p):
    """Aggiunge p pixel di bordo all'equirettangolare in modo 'sferico':
    a destra/sinistra la foto si richiude su se stessa, oltre i poli si rientra
    dall'altra parte ruotati di 180°. Serve per interpolare bene vicino ai bordi."""
    h, w = equi.shape[:2]
    sopra = np.roll(equi[:p][::-1], w // 2, axis=1)
    sotto = np.roll(equi[-p:][::-1], w // 2, axis=1)
    e = np.concatenate([sopra, equi, sotto], axis=0)
    return np.concatenate([e[:, -p:], e, e[:, :p]], axis=1)


def lato_vista_consigliato(larghezza_equi, fov, sovracampionamento=1.0):
    """Quanti pixel deve avere una vista per non perdere dettaglio rispetto al 360.
    Al centro della vista la densità di pixel coincide con quella dell'equirettangolare."""
    return int(round(np.tan(np.radians(fov) / 2) * larghezza_equi / np.pi * sovracampionamento))


def estrai_vista(equi, yaw, pitch, fov, larghezza, altezza=None, roll=0.0):
    """Ritaglia dall'equirettangolare una vista 'normale' (come una foto) nella direzione indicata."""
    altezza = altezza or larghezza
    h_e, w_e = equi.shape[:2]
    f = (larghezza / 2) / np.tan(np.radians(fov) / 2)  # lunghezza focale in pixel

    # direzione 3D di ogni pixel della vista
    jj, ii = np.meshgrid(np.arange(larghezza, dtype=np.float32),
                         np.arange(altezza, dtype=np.float32))
    x = (jj + 0.5 - larghezza / 2) / f
    y = -(ii + 0.5 - altezza / 2) / f
    z = np.ones_like(x)
    r = matrice_rotazione(yaw, pitch, roll).astype(np.float32)
    dx = r[0, 0] * x + r[0, 1] * y + r[0, 2] * z
    dy = r[1, 0] * x + r[1, 1] * y + r[1, 2] * z
    dz = r[2, 0] * x + r[2, 1] * y + r[2, 2] * z
    norma = np.sqrt(dx * dx + dy * dy + dz * dz)

    # da direzione a coordinate nell'equirettangolare
    lon = np.arctan2(dx, dz)
    lat = np.arcsin(np.clip(dy / norma, -1, 1))
    u = (lon / (2 * np.pi) + 0.5) * w_e - 0.5
    v = (0.5 - lat / np.pi) * h_e - 0.5

    p = 8
    sorgente = _bordo_equi(equi, p)
    return cv2.remap(sorgente, (u + p).astype(np.float32), (v + p).astype(np.float32),
                     interpolation=cv2.INTER_LANCZOS4, borderMode=cv2.BORDER_REPLICATE)


def metti_in_bolla(equi, pitch=0.0, roll=0.0):
    """Raddrizza un 360 inclinato: ruota la sfera di 'pitch' (avanti/indietro) e 'roll' (di lato), in gradi.
    Con 0 e 0 restituisce l'immagine così com'è."""
    if abs(pitch) < 1e-3 and abs(roll) < 1e-3:
        return equi
    h_e, w_e = equi.shape[:2]
    dx, dy, dz = _direzioni_equi(w_e, h_e)
    r = matrice_rotazione(0, pitch, roll).astype(np.float32)
    sx = r[0, 0] * dx + r[0, 1] * dy + r[0, 2] * dz
    sy = r[1, 0] * dx + r[1, 1] * dy + r[1, 2] * dz
    sz = r[2, 0] * dx + r[2, 1] * dy + r[2, 2] * dz
    u = (np.arctan2(sx, sz) / (2 * np.pi) + 0.5) * w_e - 0.5
    v = (0.5 - np.arcsin(np.clip(sy, -1, 1)) / np.pi) * h_e - 0.5
    p = 8
    return cv2.remap(_bordo_equi(equi, p), (u + p).astype(np.float32), (v + p).astype(np.float32),
                     interpolation=cv2.INTER_LANCZOS4, borderMode=cv2.BORDER_REPLICATE)


_cache_direzioni = {}


def _direzioni_equi(w_e, h_e):
    """Direzione 3D di ogni pixel dell'equirettangolare (tenuta in memoria per riusarla)."""
    chiave = (w_e, h_e)
    if chiave not in _cache_direzioni:
        _cache_direzioni.clear()
        lon = ((np.arange(w_e, dtype=np.float32) + 0.5) / w_e - 0.5) * 2 * np.pi
        lat = (0.5 - (np.arange(h_e, dtype=np.float32) + 0.5) / h_e) * np.pi
        lon, lat = np.meshgrid(lon, lat)
        _cache_direzioni[chiave] = (np.cos(lat) * np.sin(lon), np.sin(lat), np.cos(lat) * np.cos(lon))
    return _cache_direzioni[chiave]


def proietta_vista_su_equi(vista, yaw, pitch, fov, w_e, h_e, roll=0.0, potenza_peso=2.0):
    """Rimette una vista nella sua posizione dentro un equirettangolare vuoto.
    Restituisce (immagine, peso): il peso vale 1 al centro della vista e scende
    dolcemente a 0 verso i bordi, così nelle sovrapposizioni le viste si fondono."""
    altezza, larghezza = vista.shape[:2]
    t_x = np.tan(np.radians(fov) / 2)          # metà larghezza del piano immagine
    t_y = t_x * altezza / larghezza            # metà altezza del piano immagine
    f = (larghezza / 2) / t_x

    dx, dy, dz = _direzioni_equi(w_e, h_e)
    r = matrice_rotazione(yaw, pitch, roll).astype(np.float32)
    # dal mondo alla fotocamera virtuale (matrice trasposta)
    cx = r[0, 0] * dx + r[1, 0] * dy + r[2, 0] * dz
    cy = r[0, 1] * dx + r[1, 1] * dy + r[2, 1] * dz
    cz = r[0, 2] * dx + r[1, 2] * dy + r[2, 2] * dz

    davanti = cz > 1e-6
    cz_sicuro = np.where(davanti, cz, 1.0)
    px = cx / cz_sicuro                         # coordinate sul piano immagine
    py = cy / cz_sicuro
    nx = np.abs(px) / t_x                       # 0 al centro, 1 al bordo
    ny = np.abs(py) / t_y
    dentro = davanti & (nx < 1) & (ny < 1)

    peso = np.where(dentro, (1 - nx) * (1 - ny), 0).astype(np.float32) ** potenza_peso

    mappa_x = (px * f + larghezza / 2 - 0.5).astype(np.float32)
    mappa_y = (-py * f + altezza / 2 - 0.5).astype(np.float32)
    mappa_x[~dentro] = -10
    mappa_y[~dentro] = -10
    immagine = cv2.remap(vista, mappa_x, mappa_y, interpolation=cv2.INTER_LANCZOS4,
                         borderMode=cv2.BORDER_REPLICATE)
    return immagine, peso
