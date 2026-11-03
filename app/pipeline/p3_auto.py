"""
Rilievo AUTOMATICO della stanza con HorizonNet (modello open source, licenza MIT, gira sul PC, gratis).

HorizonNet guarda il 360 e trova, colonna per colonna, dove le pareti toccano soffitto e pavimento
e dove si trovano gli spigoli tra due pareti, anche dietro i mobili. Usiamo il modello addestrato
su Zillow Indoor (oltre 20.000 foto 360 di case vere).

Da qui ricaviamo i 4 angoli della stanza (pavimento e soffitto) come yaw/pitch, nello stesso formato
dei clic dell'interfaccia: il resto del rilievo (misure, guida radar, pianta) è identico.
"""
import sys
from pathlib import Path

import cv2
import numpy as np

RADICE = Path(__file__).resolve().parents[2]
CARTELLA_HN = RADICE / "terzi" / "HorizonNet"
PESI = CARTELLA_HN / "ckpt" / "resnet50_rnn__zind.pth"

_modello = None


def _carica():
    """Carica il modello una volta sola (qualche secondo) e lo tiene in memoria."""
    global _modello
    if _modello is None:
        if str(CARTELLA_HN) not in sys.path:
            sys.path.insert(0, str(CARTELLA_HN))
        import torch
        import torchvision.models as tvm
        import model as hn

        class _SenzaPesiImageNet:
            """Il codice originale chiederebbe a torchvision di scaricare i pesi ImageNet: non servono,
            perché vengono subito sostituiti da quelli di HorizonNet. Così non si scarica nulla."""
            def __getattr__(self, nome):
                costruttore = getattr(tvm, nome)
                return lambda *a, **k: costruttore(weights=None)

        hn.models = _SenzaPesiImageNet()
        dati = torch.load(str(PESI), map_location="cpu", weights_only=True)   # solo numeri, niente codice
        rete = hn.HorizonNet(**dati["kwargs"])
        rete.load_state_dict(dati["state_dict"])
        rete.eval()
        _modello = rete
    return _modello


def disponibile():
    return PESI.exists()


def trova_stanza(equi_bgr):
    """Restituisce gli angoli della stanza trovati da HorizonNet:
    {"angoli": [[yaw, pitch] x4 a terra], "soffitti": [[yaw, pitch] x4], "bordi": (soffitto, pavimento) per colonna}."""
    import torch
    from .p3_stanza import costruisci
    rete = _carica()
    from inference import inference   # funzione ufficiale di HorizonNet (post-processing incluso)
    piccola = cv2.resize(equi_bgr, (1024, 512), interpolation=cv2.INTER_AREA)

    def prova(giro, flip, rotate, base=piccola):
        # la foto si fa girare di "giro" gradi (stessa stanza vista da un altro punto di partenza)
        img = np.roll(base, int(1024 * giro / 360), axis=1)
        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        x = torch.FloatTensor(np.ascontiguousarray(rgb.transpose(2, 0, 1)[None] / 255.0))
        with torch.no_grad():
            cor_id, _, _, _ = inference(rete, x, torch.device("cpu"), flip=flip, rotate=rotate, force_cuboid=True)
        # cor_id: coppie (soffitto, pavimento) per ogni spigolo, coordinate 0-1 sull'immagine
        soffitti, angoli = [], []
        for i in range(0, len(cor_id), 2):
            for (u, v), lista in ((cor_id[i], soffitti), (cor_id[i + 1], angoli)):
                yaw = ((u - 0.5) * 360 - giro + 180) % 360 - 180
                lista.append([round(float(yaw), 3), round(float(90 - v * 180), 3)])
        s = costruisci({"altezza_camera": 1.5, "angoli": angoli, "spigoli": [], "pareti": {}, "fissi": [], "mobili": [],
                        "soffitto": soffitti[0] if soffitti else None})
        if "errore" in s:
            return None
        lati = sorted([s["XR"] - s["XL"], s["ZW"] - s["ZB"]])
        return {"scarto": s["misure"]["scarto_angoli_cm"], "lati": lati, "area": lati[0] * lati[1],
                "dati": {"angoli": angoli, "soffitti": soffitti}}

    # VOTAZIONE fra molte prove: tre versioni della foto (normale, più chiara, più contrastata), ognuna girata
    # in 4 posizioni. Specchi, vetrate e mobili possono ingannare una singola prova (armadio a specchio scuro:
    # 96 m² invece di 11; con la foto più chiara il modello vede la stanza vera). La stanza vera è quella su cui
    # concordano più prove; a parità di voti si tiene la più piccola, perché specchi e vetrate fanno sembrare
    # la stanza più grande, mai più piccola.
    versioni = [piccola, cv2.convertScaleAbs(piccola, alpha=1.15, beta=10), cv2.convertScaleAbs(piccola, alpha=1.3, beta=-30)]
    prove = [prova(g, False, [], v) for v in versioni for g in (0, 90, 180, 270)]
    valide = [p for p in prove if p and p["scarto"] <= 5]
    if not valide:
        valide = sorted([p for p in prove if p], key=lambda p: p["scarto"])[:1]
    if not valide:
        raise RuntimeError("nessuna prova del rilievo automatico è andata a buon fine")

    def simili(a, b):        # stessa stanza: entrambi i lati entro il 12%
        return all(abs(x - y) / max(x, y) <= 0.12 for x, y in zip(a["lati"], b["lati"]))
    for p in valide:
        p["voti"] = sum(simili(p, q) for q in valide)
    migliore = max(valide, key=lambda p: (p["voti"], -p["area"], -p["scarto"]))
    return migliore["dati"]
