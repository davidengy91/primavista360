# PrimaVista 360 Studio — funzionalità attuali

*Aggiornato al 2 novembre 2026*

Software locale (gira sul PC, si usa dal browser su `http://127.0.0.1:8360`) che prende una foto 360
equirettangolare (es. Insta360) e restituisce un nuovo 360 fotorealistico, con la stessa stanza, pronto per
Kuula, Facebook o qualsiasi viewer 360.

Clienti: **agenzie immobiliari, interior designer, imprese di ristrutturazione**.

---

## 1. I tre servizi (pensati per le imprese di ristrutturazione)

| Servizio | Cosa fa | Cosa serve | Costo indicativo |
|---|---|---|---|
| **Ristruttura** | Stessa disposizione, tutto rifatto: pavimenti, rivestimenti, pareti, porte e arredi nuovi al loro posto. | Foto 360 | ~0,30 € |
| **Progetta** | Nuova disposizione a misura: il cliente sceglie dove vanno cucina, sanitari, letti e mobili. Anche da stanza arredata (si svuota) o dalla sola piantina, in più varianti. | Foto 360 **o** piantina (o tutte e due) | ~0,10 € proposta + ~0,30 € a variante |
| **Prova prodotto** | Un prodotto o un materiale vero nella stanza (piastrella, mobile, sanitario): cambia solo quello, il resto resta identico al pixel. | Foto 360 | ~0,15 € a prodotto |

(I vecchi Arreda 360 e Riprogetta 360 sono confluiti in **Progetta**.)

---

## 2. Percorso guidato (pensato per l'impresa, senza istruzioni)

Una barra dei passi in alto e i pulsanti **Indietro / Avanti** in basso; ogni schermata mostra solo quello che serve.

1. **Carica**: foto 360 e/o piantina, nient'altro (se c'è la piantina: "quale stanza?").
2. **La stanza**: il 360 e la **piantina con le misure**. Da piantina si correggono quote, porte, finestre e punto del 360;
   da foto le misure sono stimate (≈) e si possono **tarare con una misura presa col metro** (parete A/B/C/D).
3. **Cosa vuoi fare**: tre scelte grandi, *Rifare tutto con i mobili al loro posto* (Ristruttura),
   *Cambiare la disposizione* (Progetta, con la domanda "la stanza ha mobili? la svuoto?"),
   *Provare solo un prodotto o un materiale* (Prova prodotto). Con la sola piantina si salta.
4. **Disposizione** (solo Progetta): proposta di Claude, pulsanti dei mobili, piantina con mobili trascinabili, varianti.
5. **Stile e materiali**: stili pronti, una nota libera, foto dei materiali e dei prodotti veri
   (in Prova prodotto: foto del prodotto + cosa farne).
6. **Genera**: riepilogo di tutto (stanza, lavoro, arredo, stile, materiali) e il pulsante per generare;
   se manca qualcosa il programma riporta al passo giusto.

Il passo a cui si era arrivati viene ricordato.

## 2a. Caricamento (passo 1)

- **Un solo caricamento** per foto 360 e piantina: il programma le riconosce da solo
  (immagine 2:1 = foto 360; PDF o altra immagine = piantina). Si possono caricare **insieme**.
- **Controllo automatico della foto**: proporzioni 2:1, risoluzione, metadati 360.
- **Solo piantina**: disponibile solo Progetta (Ristruttura e Prova prodotto hanno bisogno della stanza vera).
- **Foto + piantina**: la forma della stanza viene dalla foto, la **scala dalle misure della piantina**
  (Claude le legge, circa 0,02 €); se la forma non torna (oltre il 10%) il programma avvisa.
- **Stili pronti (preset)**, diversi per servizio:
  - *Ristruttura*: Bagno moderno, Cucina, Soggiorno, Camera, Svuota stanza, Home staging, Luxury marmo;
  - *Progetta*: Camera, Cameretta, Soggiorno, Soggiorno con pranzo, Studio, Sala da pranzo, Neutro da vendita.
    Indicano solo il tipo di stanza e lo stile: **i mobili e le misure li decide Claude** in base allo spazio reale;
  - *Prova prodotto*: nessun preset (il prodotto si sceglie dopo).
- **Testo libero** per descrivere cosa si vuole ottenere.

---

## 2b. Progetto da piantina (senza foto 360)

- Nella pagina **Nuovo progetto** si carica solo la piantina: un **PDF o un'immagine** della pianta
  (anche una foto), si scrive **quale stanza** (es. "camera matrimoniale") e come la si vuole.
- **Claude legge la piantina** (circa 0,02 €): misure interne, altezza, porte, finestre e porte-finestre con
  posizione e misura; se una quota manca o la stanza non è rettangolare lo scrive nelle note.
- Il programma **costruisce la stanza in scala** e la mostra come **modellino 360** (pareti grigie, vetri azzurri,
  porte, mobili a blocchi a misura).
- **Editor della piantina** sotto il 360:
  - larghezza, profondità e altezza in cm, modificabili;
  - porte e finestre: tipo, parete, distanza dall'angolo, larghezza, altezza, davanzale; aggiungi o togli;
  - **punto di ripresa** del 360 (punto oro) da trascinare;
  - **mobili trascinabili** con mouse o dito; nomi delle pareti A/B/C/D come sul 360;
  - link alla piantina originale per confronto.
- Arredo come in Progetta (proposta di Claude, pulsanti, varianti, foto dei prodotti e dei materiali).
- **Render**: a ChatGPT va solo la base pulita, con un prompt di *resa* (stessa geometria, colori della base
  spiegati, mobili dentro i loro blocchi); risultato portato a 7680 px con metadati 360.

## 2c. Svuota stanza (stanze arredate)

- In Progetta, su una foto 360 arredata: **🧹 Svuota la stanza** (circa 0,10–0,25 €).
- ChatGPT toglie mobili e oggetti e tiene pareti, pavimento, porte, finestre e impianti.
- La stanza vuota diventa la **base del progetto** e il **rilievo viene rifatto** (senza mobili è più preciso);
  la foto arredata originale resta salvata. Si può rifare lo svuotamento.

## 3. Misura automatica della stanza (gratis, sul PC)

- **Rilievo automatico** con HorizonNet (modello open source addestrato su 20.000 case vere): trova pareti,
  pavimento e soffitto in pochi secondi, appena caricata la foto.
- **Votazione fra 12 prove** (foto normale, più chiara e più contrastata, ognuna girata in 4 posizioni): si tiene la
  stanza su cui concordano più prove, a parità la più piccola. Regge stanze piene di mobili e **specchi**
  (camera con armadio a specchio scuro: da 96 m² sbagliati a 11 m² corretti). Circa 4 secondi.
- **Correzione a mano semplice** (passo "La stanza"): nel 360 le **linee oro** mostrano le pareti trovate; nella piantina
  le **pareti si trascinano** e le linee nel 360 si aggiornano. Avviso se le misure sembrano troppo grandi
  (oltre 40 m² o un lato oltre 8 m).
- **Scala della stanza**:
  - con una porta segnata: taratura sull'altezza della porta (2,10 m);
  - senza porta: taratura sul soffitto a 2,70 m (altezza tipica delle abitazioni).
  Nelle prove la fotocamera risulta tra 1,0 e 1,3 m, coerente con le misure reali.
- **Controllo di affidabilità**: se la stanza ricostruita non torna (scarto oltre 20 cm), in **Progetta**
  compare un avviso e il programma **non genera**, per non spendere su un risultato sbagliato.
- **Le misure non vengono mostrate al cliente** finché non saranno verificate con il metro laser.
- La **guida "radar"** (griglia, blocchi dei mobili, elementi fissi in rosso) è **interna**: la usa il programma
  per guidare ChatGPT, il cliente non la vede mai.

---

## 4. Pagina "Prepara la stanza" (semplice, per il cliente)

Una sola pagina con la foto 360 navigabile, i passi spiegati in 3 righe e **un solo pulsante** per generare.
Ogni servizio mostra solo quello che gli serve.

### Comune a tutti
- **Etichette "Parete A / B / C / D"** sulla foto, per sapere a quale parete corrisponde ogni scheda materiale.
- **Materiali (facoltativi)** con foto vere da trascinare:
  pavimento, tutte le pareti, singola parete A/B/C/D, rivestimento fino a un'altezza (90–270 cm),
  soffitto, porte interne, moodboard (stile e palette). Per ogni foto si può aggiungere una nota
  (modello, colore, finitura).
- **Controlli prima di spendere**: se manca qualcosa il pulsante non parte e un messaggio ben visibile spiega
  cosa fare.
- **Conferma prima di ogni spesa**, con il costo indicativo.

### Ristruttura
- Solo la foto e i materiali facoltativi, poi **Genera il 360**.

### Prova prodotto (senza ritagli)
- Per ogni prodotto una scheda con:
  - la **foto del prodotto** (es. dal sito del produttore);
  - il campo **"Cosa vuoi fare con questo prodotto?"**
    (es. "Sostituisci il letto con questo", "Aggiungi questa poltrona nell'angolo vicino alla finestra").
- **+ Aggiungi un altro prodotto** per provarne più di uno.
- Pulsante **Prova nella stanza**.

### Progetta
- **✨ Proponi arredo con Claude**: Claude progetta posizione e misura di ogni mobile sulla stanza vera.
  Il programma verifica la proposta e, se serve, la fa correggere (massimo 2 chiamate):
  - niente mobili sovrapposti;
  - porte e passaggi liberi (0,7 m davanti ad armadi e cucine);
  - letto con almeno un lato libero e spazio ai piedi;
  - mobili non troppo vicini alla fotocamera (sembrerebbero enormi);
  - stanza non troppo piena (massimo 45% del pavimento).
- **Pulsanti rapidi** per aggiungere i mobili a mano (letto matrimoniale, letto singolo, comodino, armadio,
  divano, poltrona, tavoli, sedia, basi cucina, mobile bagno, doccia, tappeto…): un clic sul pavimento dove vanno.
- **Elenco mobili con misure in cm** modificabili, rotazione, "al muro", foto del prodotto vero per ogni mobile.
- **Nome dei mobili sulla foto**, nel punto dove andranno.
- **Varianti A, B, C…** (fino a 5): nuova variante vuota o duplicata.

---

## 5. Come lavora l'intelligenza artificiale

### Ristruttura e Progetta (360 intero)
- A ChatGPT vanno sempre **la foto, la guida interna e un prompt strutturato** (capitolato, mobili con misure,
  elementi da non toccare).
- **Maschera di protezione** di porte, finestre ed elementi fissi.
- Dopo la generazione:
  - **riallineamento** automatico al pixel;
  - **porte e finestre** rimesse dalla foto originale dove combaciano;
  - **controllo fedeltà geometrica** (confronto dei bordi con la foto vera, in percentuale);
  - **giunzione 0°/360°** controllata e corretta solo se serve.

### Prova prodotto (nuovo metodo)
1. **Claude trova la zona** dalla frase del cliente e dalla foto del prodotto: l'oggetto da sostituire per intero
   (con testiera, gambe…) oppure lo spazio dove aggiungerlo. Circa 1 centesimo, fatto per tutti i prodotti
   **prima** di spendere per le immagini; se non trova nulla si ferma e chiede di scrivere meglio.
2. **Vista prospettica dritta** centrata sulla zona: ChatGPT vede l'oggetto senza la deformazione del 360.
3. **ChatGPT lavora libero** in un'area ampia attorno all'oggetto, con la foto del prodotto vero.
4. **Torna nel 360 solo ciò che è cambiato davvero**, con bordi netti: il resto è la foto originale al pixel.
5. File di controllo salvati nel progetto: zona trovata da Claude, vista prima/dopo, zona reinserita.

### Rifinitura finale (gratis, sul PC)
- **Nitidezza AI** con Real-ESRGAN: porta il risultato da 3840 px alla risoluzione dell'originale (fino a 12K),
  circa 1 minuto.
- **Metadati 360 (GPano)** scritti nel JPG: si apre subito come 360 su Kuula, Facebook, ecc.
- **Nadir** lasciato com'è; se si mette un `logo.png` nella cartella `config/`, viene coperto da un disco col logo.

---

## 6. Avanzamento e consegna

- **Pagina di avanzamento** con le fasi in tempo reale.
- **Consegna** con viewer 360:
  - **Confronto** prima/dopo con tendina, **Prima**, **Dopo**;
  - **Bordi**: i bordi della foto vera sopra il risultato, per controllare che porte e finestre coincidano;
  - selettore delle **varianti** A/B/C.
- **Correzioni rapide** con frasi pronte (circa 0,10 € l'una):
  dimensioni della stanza cambiate, porta/finestra spostata, griglia copiata, mobile troppo grande,
  oggetti non richiesti, pavimento non cambiato, bordi destro/sinistro che non combaciano;
  oppure **correzione scritta a mano**.
- **Download** del JPG 360 con metadati e dell'immagine **prima/dopo**.
- **Apri cartella** del progetto e **Rifai** (stesso lavoro, stessa foto, nuovo progetto).
- **Costi reali** di ogni progetto registrati in `costi.json` e mostrati nella consegna.

---

## 7. Progetti, costi e sicurezza

- **Pagina Progetti** con l'elenco dei lavori e le miniature.
- **Tetto di spesa per progetto**: 5 € (`SPESA_MASSIMA_EURO` nel file `.env`).
- **Nessuna spesa senza conferma**: ogni chiamata a pagamento parte solo dal clic del fotografo.
- **Chiavi API** solo nel file `.env`, che resta sul PC.
- **Prezzi** aggiornabili a mano in `config/prezzi.json`.
- **Ricarica automatica** della pagina quando il programma viene aggiornato.

---

## 8. Strumenti tecnici (solo per noi)

Aprendo la pagina con `?avanzati` nell'indirizzo (es. `http://127.0.0.1:8360/?avanzati#/rilievo/…`)
compaiono gli strumenti di rilievo a mano, invisibili al cliente:

- angoli a terra, spigoli, battiscopa, soffitto, porte e finestre;
- **Sposta linee**: trascinare le pareti della guida con mouse o dito;
- vista **Guida radar**, altezza della fotocamera, bolla, taratura con la porta, misure della stanza.

---

## 9. Modelli e tecnologie

| Cosa | Dove gira | Licenza |
|---|---|---|
| ChatGPT immagini (`gpt-image-2.5-sunburst`) | online, a pagamento | — |
| Claude (`claude-opus-5-5`): proposta arredo, ricerca della zona | online, a pagamento | — |
| HorizonNet (rilievo stanza) | sul PC, gratis | MIT |
| Real-ESRGAN (nitidezza) | sul PC, gratis | BSD |

Programma in Python (FastAPI) con pagina web; si avvia con doppio clic su `avvia.bat`.

---

## 10. Stato delle prove

| Funzione | Stato |
|---|---|
| Ristruttura | provato con generazioni reali |
| Rilievo automatico + taratura soffitto | provato su tutte le foto dei progetti |
| Prova prodotto: reinserimento di ciò che è cambiato | provato sul letto già generato da ChatGPT (risultato approvato) |
| Prova prodotto: ricerca della zona con Claude | provato solo con AI simulate: **manca la prima prova reale** |
| Progetta: proposta di Claude | provata (bagno, cameretta) |
| Progetta: generazione | **manca la prima prova reale** |
| Progetto da piantina: lettura di Claude | provato solo con dati simulati: **manca la prima prova reale** |
| Progetto da piantina: editor, modellino, render | provato con ChatGPT simulato, fino al JPG 360 finale |
| Svuota stanza | provato con ChatGPT simulato: **manca la prima prova reale** |
| Misure della stanza in metri | non verificate con il metro laser (per questo nascoste al cliente) |

## 11. Idee per il futuro (non ancora fatte)

- Stanze non rettangolari (a L, con nicchie), sia da foto sia da piantina.
- Modellino 3D navigabile (Three.js) con catalogo a misura e attacchi impianti (scarichi, acqua, prese, luci).
- Quote modificabili anche nei progetti da foto 360.
- Mobili 3D dalle foto dei prodotti con Meshy.

- Pianta quotata in PDF (da discutere).
- Verifica delle misure con metro laser, poi computo dei lavori.
- Catalogo prodotti dell'impresa.
- Logo PrimaVista nel nadir.
