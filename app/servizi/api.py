"""
Collegamento alle API di OpenAI (immagini) e Anthropic (Claude).
Le chiavi vengono lette dal file .env, mai scritte nel codice.
Gli errori temporanei (rete, sovraccarico, limiti di velocità) vengono ritentati in automatico.
"""
import base64
import io
import logging
import os
import time
from pathlib import Path

import anthropic
import cv2
import numpy as np
import openai
from dotenv import load_dotenv

RADICE = Path(__file__).resolve().parents[2]
load_dotenv(RADICE / ".env")
log = logging.getLogger("primavista")

TENTATIVI = 4          # quante volte riprovare un errore temporaneo
ATTESA_INIZIALE = 10   # secondi di attesa dopo il primo errore (poi raddoppia)


def _con_retry(funzione, descrizione):
    """Esegue la chiamata e, se fallisce per un motivo temporaneo, aspetta e riprova."""
    attesa = ATTESA_INIZIALE
    for tentativo in range(1, TENTATIVI + 1):
        try:
            return funzione()
        except (openai.RateLimitError, openai.APIConnectionError, openai.InternalServerError,
                anthropic.RateLimitError, anthropic.APIConnectionError, anthropic.InternalServerError) as e:
            if tentativo == TENTATIVI:
                log.error("%s: fallito dopo %d tentativi: %s", descrizione, TENTATIVI, e)
                raise
            log.warning("%s: errore temporaneo (%s). Riprovo tra %d s (tentativo %d/%d)",
                        descrizione, type(e).__name__, attesa, tentativo + 1, TENTATIVI)
            time.sleep(attesa)
            attesa *= 2
        except (openai.APIStatusError, anthropic.APIStatusError) as e:
            # errori "definitivi" (richiesta sbagliata, chiave non valida, contenuto rifiutato...)
            log.error("%s: errore API %s: %s", descrizione, getattr(e, "status_code", "?"), e)
            raise


# ------------------------------------------------------------------ OpenAI (immagini)

_client_openai = None


def client_openai():
    global _client_openai
    if _client_openai is None:
        _client_openai = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"), timeout=600, max_retries=0)
    return _client_openai


def png_bytes(img, nome="immagine.png"):
    """Converte un'immagine (array opencv) in un file PNG in memoria, pronto da inviare."""
    ok, dati = cv2.imencode(".png", img)
    f = io.BytesIO(dati.tobytes())
    f.name = nome
    return f


def modifica_immagine(immagini, prompt, maschera, modello, lato, qualita, registro, descrizione, dimensione=None):
    """Chiama l'endpoint 'edit' di OpenAI.
    immagini: lista di array opencv; la PRIMA è quella da modificare, le altre sono riferimenti.
    maschera: array RGBA (stessa misura della prima) con trasparenza dove modificare, oppure None.
    Restituisce l'immagine generata (array opencv BGR)."""
    file_immagini = [png_bytes(im, f"img_{i}.png") for i, im in enumerate(immagini)]
    # dimensione: "LARGHEZZAxALTEZZA" per immagini non quadrate (es. "2048x1024" per un 360)
    parametri = dict(model=modello, image=file_immagini, prompt=prompt, size=dimensione or f"{lato}x{lato}",
                     quality=qualita, output_format="png", n=1)
    if maschera is not None:
        parametri["mask"] = png_bytes(maschera, "maschera.png")

    def chiama():
        for f in file_immagini + ([parametri["mask"]] if "mask" in parametri else []):
            f.seek(0)
        return client_openai().images.edit(**parametri)

    inizio = time.time()
    risposta = _con_retry(chiama, descrizione)
    registro.registra_openai(modello, getattr(risposta, "usage", None), time.time() - inizio, descrizione)
    dati = base64.b64decode(risposta.data[0].b64_json)
    return cv2.imdecode(np.frombuffer(dati, np.uint8), cv2.IMREAD_COLOR)


# ------------------------------------------------------------------ Anthropic (Claude)

_client_anthropic = None


def client_anthropic():
    global _client_anthropic
    if _client_anthropic is None:
        _client_anthropic = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"), max_retries=0)
    return _client_anthropic


def blocco_immagine(img, lato_max=768, qualita=88):
    """Prepara un'immagine da mostrare a Claude (ridotta e in JPG per risparmiare token)."""
    h, w = img.shape[:2]
    scala = min(1.0, lato_max / max(h, w))
    if scala < 1:
        img = cv2.resize(img, (int(w * scala), int(h * scala)), interpolation=cv2.INTER_AREA)
    ok, dati = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, qualita])
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                        "data": base64.standard_b64encode(dati.tobytes()).decode()}}


def chiedi_a_claude(contenuto, schema, sistema, modello, registro, descrizione, sforzo="high"):
    """Manda a Claude testo+immagini e riceve una risposta strutturata (oggetto pydantic 'schema')."""
    def chiama():
        # "stream" = la risposta arriva a pezzi: evita i timeout sulle risposte lunghe
        with client_anthropic().messages.stream(
            model=modello,
            max_tokens=32000,
            system=sistema,
            messages=[{"role": "user", "content": contenuto}],
            output_format=schema,
            output_config={"effort": sforzo},
            # se Claude rifiuta per un falso allarme di sicurezza, la richiesta passa a un altro modello
            extra_headers={"anthropic-beta": "server-side-fallback-2026-07-01"},
            extra_body={"fallbacks": "default"},
        ) as stream:
            return stream.get_final_message()

    inizio = time.time()
    risposta = _con_retry(chiama, descrizione)
    registro.registra_anthropic(modello, risposta.usage, time.time() - inizio, descrizione)
    if risposta.stop_reason == "refusal":
        raise RuntimeError(f"{descrizione}: Claude ha rifiutato la richiesta")
    if risposta.parsed_output is None:
        raise RuntimeError(f"{descrizione}: risposta di Claude non leggibile (stop: {risposta.stop_reason})")
    return risposta.parsed_output
