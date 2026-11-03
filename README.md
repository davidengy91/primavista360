# PrimaVista 360 Studio

Ristrutturazione e arredo virtuale **sulle foto 360**, per agenzie immobiliari, interior designer e imprese
di ristrutturazione. Si carica un 360 equirettangolare (es. Insta360), si sceglie il servizio e si ottiene
un nuovo 360 fotorealistico, con la stessa stanza, le stesse porte e finestre, pronto per Kuula, Facebook
o qualsiasi viewer (metadati 360 inclusi).

---

## I tre servizi

| Servizio | Cosa fa | Cosa serve |
|---|---|---|
| **Ristruttura** | Stessa disposizione, tutto rifatto: pavimenti, rivestimenti, pareti, porte e arredi nuovi al loro posto. | Foto 360 |
| **Progetta** | Nuova disposizione a misura: il cliente sceglie dove vanno cucina, sanitari, letti e mobili. Anche da stanza arredata (si svuota) o dalla sola piantina. | Foto 360 o piantina |
| **Prova prodotto** | Un prodotto o un materiale vero nella stanza: cambia solo quello, il resto resta identico al pixel. | Foto 360 |

Foto 360 e piantina si possono caricare insieme: la piantina dà le misure vere alla stanza della foto.

## Installazione (una volta sola)

1. Serve **Python 3.11 o più recente** (su questo PC c'è già il 3.13).
2. Fai doppio clic su **`avvia.bat`**: la prima volta crea l'ambiente e installa tutto (qualche minuto).
3. I modelli locali sono nella cartella `terzi/` (gratis, girano sul PC, licenze libere anche per uso commerciale):
   - **HorizonNet** (MIT): trova pareti, pavimento e soffitto della stanza;
   - **Real-ESRGAN** (BSD): porta il risultato alla risoluzione dell'originale (fino a 12K) con dettagli nitidi.

## Le chiavi API

Apri il file **`.env`** con il Blocco note e incolla le chiavi dopo il simbolo `=` (senza spazi né virgolette):

```
OPENAI_API_KEY=...        (da https://platform.openai.com/api-keys)
ANTHROPIC_API_KEY=...     (da https://console.anthropic.com/settings/keys)
SPESA_MASSIMA_EURO=5      (tetto di spesa per progetto)
```

Il file `.env` resta solo sul tuo computer: non condividerlo. Per controllare che le chiavi funzionino fai
doppio clic su **`prova_chiavi.bat`** (gratis).

## Avvio

Doppio clic su **`avvia.bat`**: si apre il browser su **http://127.0.0.1:8360**.
Lascia aperta la finestra nera mentre lavori; per chiudere il programma chiudi la finestra.

## Come si usa

1. **Nuovo progetto**: carica il 360, scegli il servizio, scrivi cosa vuoi ottenere.
2. **Rilievo** (gratis, circa 1 minuto): il programma trova da solo pareti, pavimento e soffitto e li disegna
   sulla foto (guida "radar"). Controlla che le linee cadano sugli spigoli veri; se serve:
   - **Sposta linee**: trascina le maniglie (angoli, centro delle pareti, soffitto) con il mouse o il dito;
   - **Spigoli / Battiscopa / Cancella punto**: correzioni con un clic.
   Segna almeno **una porta** e attiva **"Tara con la porta"**: le proporzioni dei mobili saranno corrette.
3. **Arredo e prodotti reali** (sotto il 360):
   - aggiungi i mobili con i pulsanti rapidi e clicca sul pavimento dove vanno (misure, rotazione, "al muro");
   - in Progetta usa **✨ Proponi arredo con Claude**: posizione e misura di ogni mobile, verificate;
   - in Prova prodotto carica la foto del prodotto e **scrivi cosa vuoi fare** (es. "sostituisci il letto con
     questo"): il programma trova da solo il punto nella foto (Claude, circa 1 centesimo);
   - trascina sulle schede le **foto dei prodotti veri** (es. il letto dal sito del produttore) e dei
     **materiali**: pavimento, tutte le pareti o una sola (A, B, C, D), rivestimento fino a un'altezza,
     soffitto, porte interne, moodboard.
4. **Conferma rilievo**, poi **Genera** (il programma chiede conferma prima di spendere).
5. **Consegna**: confronto prima/dopo a 360, vista "Bordi" per controllare che porte e finestre coincidano,
   varianti A/B/C, correzioni rapide, download del JPG 360 con metadati e della cartella del progetto.

Il nadir (sotto la fotocamera) resta quello della foto. Per coprirlo con un disco col tuo logo salva un file
**`logo.png`** nella cartella `config/`.

## Costi indicativi (per foto)

| Voce | Costo |
|---|---|
| Rilievo, guida radar, controlli, nitidezza 12K | gratis (sul PC) |
| Ristruttura / Progetta (ChatGPT, 3840 px alta qualità) | circa 0,10–0,35 € |
| Prova prodotto | circa 0,10–0,15 € |
| Proposta d'arredo di Claude | circa 0,05–0,15 € |
| Ogni correzione rapida | circa 0,10 € |

Tutti i costi reali sono registrati nel file `costi.json` di ogni progetto e mostrati nella consegna.
I prezzi delle API si aggiornano a mano in `config/prezzi.json`.

## Misure

Il programma ricostruisce la stanza in metri per disegnare la guida e proporzionare i mobili, ma **le misure
non vengono mostrate al cliente** finché non sono state verificate su stanze misurate con il metro laser.
La precisione dipende dall'altezza della fotocamera: usa sempre la taratura con la porta.

## Cartelle

```
app/            programma (server, pagina web, procedure)
config/         impostazioni, prezzi, eventuale logo.png
progetti/       un progetto per lavoro: foto, guida, risultati, costi, registro
terzi/          modelli locali (HorizonNet, Real-ESRGAN)
test/           prove automatiche senza AI (geometria, stanza, chiavi)
```

Le prove senza AI si lanciano con:

```
.venv\Scripts\python test\test_taglio_ricomposizione.py
.venv\Scripts\python test\test_stanza.py
```

## Per il team: installare da GitHub

1. Clona il repository **con i sottomoduli**: `git clone --recurse-submodules <indirizzo del repository>`
2. Copia `.env.example` in `.env` e metti **le tue** chiavi API (OpenAI, Anthropic, Meshy).
   Il file `.env` non va mai su GitHub: è escluso da `.gitignore`.
3. I modelli AI pesanti non stanno su GitHub (superano i 100 MB). Chiedili a Davide e copiali qui:
   - `terzi/HorizonNet/ckpt/resnet50_rnn__zind.pth` (rilievo automatico della stanza dalla foto 360)
   - `terzi/esrgan/realesr-general-x4v3.pth` (ingrandimento finale a 8K)
4. Per il render 3D serve **Blender 5.2** installato nella cartella standard.
5. Avvia con `avvia.bat`.

Non vanno su GitHub nemmeno i dati: `progetti/`, `case/`, `catalogo/` (foto e modelli dei clienti) e `backup/`.
