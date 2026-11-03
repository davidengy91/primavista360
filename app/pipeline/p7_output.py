"""
Passo 7 - Output: salva il JPG 360 con i metadati che lo fanno riconoscere come foto sferica
(GPano XMP, lo standard usato da Google, Facebook, Kuula, Pannellum...).
Copia anche i dati EXIF dell'originale (fotocamera, data di scatto).
"""
import io
import re

from PIL import Image

INTESTAZIONE_XMP = b"http://ns.adobe.com/xap/1.0/\x00"


def _segmenti_jpeg(dati):
    """Scorre i blocchi iniziali di un file JPEG: restituisce (marcatore, inizio, fine)."""
    pos = 2  # salta FFD8 (inizio file)
    while pos < len(dati) - 4 and dati[pos] == 0xFF:
        marcatore = dati[pos + 1]
        if marcatore == 0xDA:  # inizio dei dati immagine: fine dei blocchi di intestazione
            break
        lunghezza = int.from_bytes(dati[pos + 2:pos + 4], "big")
        yield marcatore, pos, pos + 2 + lunghezza
        pos += 2 + lunghezza


def leggi_xmp(percorso):
    """Restituisce il testo XMP contenuto nel JPG (o None se non c'è)."""
    with open(percorso, "rb") as f:
        dati = f.read()
    for marcatore, inizio, fine in _segmenti_jpeg(dati):
        contenuto = dati[inizio + 4:fine]
        if marcatore == 0xE1 and contenuto.startswith(INTESTAZIONE_XMP):
            return contenuto[len(INTESTAZIONE_XMP):].decode("utf-8", errors="replace")
    return None


def leggi_gpano(percorso):
    """Legge i campi GPano (es. ProjectionType) dal JPG. Dizionario vuoto se non è marcato come 360."""
    xmp = leggi_xmp(percorso) or ""
    campi = dict(re.findall(r'GPano:(\w+)="([^"]*)"', xmp))
    campi.update(re.findall(r"<GPano:(\w+)>([^<]*)</GPano:\w+>", xmp))
    return campi


def crea_xmp_gpano(larghezza, altezza, campi_originali=None):
    """Prepara il blocco XMP GPano per un equirettangolare completo."""
    campi = {
        "UsePanoramaViewer": "True",
        "ProjectionType": "equirectangular",
        "FullPanoWidthPixels": str(larghezza),
        "FullPanoHeightPixels": str(altezza),
        "CroppedAreaImageWidthPixels": str(larghezza),
        "CroppedAreaImageHeightPixels": str(altezza),
        "CroppedAreaLeftPixels": "0",
        "CroppedAreaTopPixels": "0",
    }
    # mantiene l'orientamento originale della fotocamera se c'era
    for chiave in ("PoseHeadingDegrees", "PosePitchDegrees", "PoseRollDegrees", "InitialViewHeadingDegrees"):
        if campi_originali and chiave in campi_originali:
            campi[chiave] = campi_originali[chiave]
    attributi = "\n".join(f'    GPano:{k}="{v}"' for k, v in campi.items())
    xmp = (
        '<?xpacket begin="﻿" id="W5M0MpCehiHzreSzNTczkc9d"?>\n'
        '<x:xmpmeta xmlns:x="adobe:ns:meta/" x:xmptk="PrimaVista 360 AI">\n'
        ' <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">\n'
        '  <rdf:Description rdf:about="" xmlns:GPano="http://ns.google.com/photos/1.0/panorama/"\n'
        f"{attributi}/>\n"
        " </rdf:RDF>\n"
        "</x:xmpmeta>\n"
        '<?xpacket end="w"?>'
    )
    return xmp.encode("utf-8")


def salva_jpg_360(immagine_bgr, percorso, originale=None, qualita=95):
    """Salva l'equirettangolare come JPG 360 con metadati GPano (+ EXIF dell'originale se indicato)."""
    altezza, larghezza = immagine_bgr.shape[:2]
    pil = Image.fromarray(immagine_bgr[..., ::-1])  # da BGR (opencv) a RGB
    exif = b""
    campi_originali = {}
    if originale:
        with Image.open(originale) as o:
            exif = o.info.get("exif", b"")
        campi_originali = leggi_gpano(originale)

    buffer = io.BytesIO()
    # subsampling=0 = colori a piena risoluzione (4:4:4), meglio per la qualità
    pil.save(buffer, "JPEG", quality=qualita, subsampling=0, exif=exif)
    dati = buffer.getvalue()

    # inserisce il blocco XMP subito dopo i blocchi iniziali (APP0/EXIF)
    punto = 2
    for marcatore, _inizio, fine in _segmenti_jpeg(dati):
        if 0xE0 <= marcatore <= 0xEF:
            punto = fine
        else:
            break
    contenuto = INTESTAZIONE_XMP + crea_xmp_gpano(larghezza, altezza, campi_originali)
    blocco = b"\xFF\xE1" + (len(contenuto) + 2).to_bytes(2, "big") + contenuto
    with open(percorso, "wb") as f:
        f.write(dati[:punto] + blocco + dati[punto:])
