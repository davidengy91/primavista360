"""
Registro dei costi: per ogni chiamata API annota token, tempo e costo stimato.
Se la spesa del progetto supera il tetto (SPESA_MASSIMA_EURO nel .env) blocca il lavoro.
"""
import json
import threading
import time
from pathlib import Path

RADICE = Path(__file__).resolve().parents[2]


class BudgetSuperato(Exception):
    """Sollevata quando una nuova chiamata farebbe superare la spesa massima."""


class RegistroCosti:
    def __init__(self, file_json, spesa_massima_euro):
        self.file_json = Path(file_json)
        self.spesa_massima = float(spesa_massima_euro)
        self.prezzi = json.loads((RADICE / "config" / "prezzi.json").read_text(encoding="utf-8"))
        self.chiamate = []
        self._lock = threading.Lock()

    # ---- totali ----
    def totale_euro(self, servizio=None):
        return sum(c["costo_euro"] for c in self.chiamate if servizio in (None, c["servizio"]))

    def controlla(self, stima_euro, descrizione):
        """Da chiamare PRIMA di una chiamata API: blocca se si sforerebbe il tetto."""
        if self.totale_euro() + stima_euro > self.spesa_massima:
            raise BudgetSuperato(
                f"Spesa massima raggiunta: spesi {self.totale_euro():.2f} €, "
                f"la chiamata '{descrizione}' costerebbe circa {stima_euro:.2f} € "
                f"(tetto {self.spesa_massima:.2f} €)."
            )

    # ---- registrazione ----
    def _salva(self, voce):
        with self._lock:
            self.chiamate.append(voce)
            riepilogo = {
                "totale_euro": round(self.totale_euro(), 4),
                "openai_euro": round(self.totale_euro("openai"), 4),
                "anthropic_euro": round(self.totale_euro("anthropic"), 4),
                "numero_chiamate": len(self.chiamate),
                "spesa_massima_euro": self.spesa_massima,
                "chiamate": self.chiamate,
            }
            self.file_json.write_text(json.dumps(riepilogo, indent=2, ensure_ascii=False), encoding="utf-8")

    def registra_openai(self, modello, usage, secondi, descrizione):
        p = self.prezzi["openai"].get(modello, next(iter(self.prezzi["openai"].values())))
        testo = immagini_in = immagini_out = 0
        if usage is not None:
            dettagli = getattr(usage, "input_tokens_details", None)
            testo = getattr(dettagli, "text_tokens", 0) or 0
            immagini_in = getattr(dettagli, "image_tokens", 0) or 0
            if not dettagli:
                testo = getattr(usage, "input_tokens", 0) or 0
            immagini_out = getattr(usage, "output_tokens", 0) or 0
        usd = (testo * p["testo_input"] + immagini_in * p["immagine_input"] + immagini_out * p["immagine_output"]) / 1e6
        self._salva({"servizio": "openai", "modello": modello, "descrizione": descrizione,
                     "token_testo": testo, "token_immagini_input": immagini_in, "token_output": immagini_out,
                     "secondi": round(secondi, 1), "costo_euro": round(usd * self.prezzi["cambio_usd_eur"], 4),
                     "ora": time.strftime("%H:%M:%S")})

    def registra_anthropic(self, modello, usage, secondi, descrizione):
        p = self.prezzi["anthropic"].get(modello, next(iter(self.prezzi["anthropic"].values())))
        ingresso = (usage.input_tokens or 0) + (getattr(usage, "cache_creation_input_tokens", 0) or 0) \
            + (getattr(usage, "cache_read_input_tokens", 0) or 0)
        uscita = usage.output_tokens or 0
        usd = (ingresso * p["input"] + uscita * p["output"]) / 1e6
        self._salva({"servizio": "anthropic", "modello": modello, "descrizione": descrizione,
                     "token_input": ingresso, "token_output": uscita, "secondi": round(secondi, 1),
                     "costo_euro": round(usd * self.prezzi["cambio_usd_eur"], 4),
                     "ora": time.strftime("%H:%M:%S")})
