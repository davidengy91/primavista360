"""
Tester delle chiavi API: controlla che le chiavi nel file .env funzionino.
Non genera immagini e non scrive testi: legge solo l'elenco dei modelli, quindi è GRATIS.

Uso:  python test/test_chiavi.py
"""
import os
from pathlib import Path

from dotenv import load_dotenv

RADICE = Path(__file__).resolve().parents[1]
load_dotenv(RADICE / ".env")


def prova_openai():
    chiave = os.getenv("OPENAI_API_KEY", "").strip()
    if not chiave:
        return "MANCA la chiave OPENAI_API_KEY nel file .env"
    from openai import OpenAI
    try:
        modelli = sorted(m.id for m in OpenAI(api_key=chiave).models.list())
    except Exception as e:  # noqa: BLE001
        return f"ERRORE: {e}"
    immagini = [m for m in modelli if "image" in m]
    return f"OK - {len(modelli)} modelli disponibili. Modelli immagine: {', '.join(immagini) or 'NESSUNO (serve la verifica organizzazione?)'}"


def prova_anthropic():
    chiave = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not chiave:
        return "MANCA la chiave ANTHROPIC_API_KEY nel file .env"
    import anthropic
    try:
        modelli = [m.id for m in anthropic.Anthropic(api_key=chiave).models.list(limit=20)]
    except Exception as e:  # noqa: BLE001
        return f"ERRORE: {e}"
    return f"OK - modelli Claude disponibili: {', '.join(modelli)}"


if __name__ == "__main__":
    print("OpenAI:   ", prova_openai())
    print("Anthropic:", prova_anthropic())
