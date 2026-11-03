// PrimaVista 360 AI - logica della pagina (schermate: nuovo, lavoro, consegna, progetti)

const $ = (sel, radice = document) => radice.querySelector(sel);
const pagina = $("#pagina");
let FASI = {};
let PRESET = [];

// messaggio ben visibile in basso (errori e conferme): resta qualche secondo
function mostraMessaggio(testo, tipo = "attenzione") {
  let box = document.querySelector("#messaggio-flottante");
  if (!box) { box = document.createElement("div"); box.id = "messaggio-flottante"; document.body.appendChild(box); }
  box.className = `messaggio-flottante ${tipo}`;
  box.textContent = testo;
  box.hidden = false;
  clearTimeout(box._timer);
  box._timer = setTimeout(() => { box.hidden = true; }, 6000);
}
let PRESET_ARREDO = [];
let CORREZIONI = {};
let timerAttivi = [];
let viewerAttivi = [];

const euro = (n) => (n || 0).toLocaleString("it-IT", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + " €";
const durata = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

function pulisci() {
  timerAttivi.forEach(clearInterval);
  timerAttivi = [];
  viewerAttivi.forEach((v) => { try { v.destroy(); } catch (e) { /* già chiuso */ } });
  viewerAttivi = [];
}

function mostra(idModello) {
  pulisci();
  if (idModello !== "#t-rilievo") document.body.classList.remove("mostra-avanzati");
  pagina.innerHTML = "";
  pagina.appendChild($(idModello).content.cloneNode(true));
}

function viewer(elemento, url, extra = {}) {
  const v = pannellum.viewer(elemento, {
    type: "equirectangular", panorama: url, autoLoad: true, showControls: false,
    // grandangolo come l'app Insta360: si parte larghi (115°) e si può allargare fino a 135° con la rotellina
    hfov: 115, minHfov: 40, maxHfov: 135, yaw: 0, pitch: 0, friction: 0.18, ...extra,
  });
  viewerAttivi.push(v);
  return v;
}

function chiediConferma(titolo, testo, ok = "Conferma") {
  // finestra di conferma disegnata nella pagina (quella del browser non funziona ovunque)
  return new Promise((risolvi) => {
    const sfondo = document.createElement("div");
    sfondo.className = "modale-sfondo";
    sfondo.innerHTML = `<div class="modale"><strong>${titolo}</strong><p>${testo}</p>
      <div class="azioni"><button class="bottone" data-r="0">Annulla</button>
      <button class="bottone primario" data-r="1">${ok}</button></div></div>`;
    sfondo.addEventListener("click", (e) => {
      const r = e.target.dataset.r;
      if (r === undefined && e.target !== sfondo) return;
      sfondo.remove();
      risolvi(r === "1");
    });
    document.body.appendChild(sfondo);
  });
}

async function api(url, opzioni) {
  const r = await fetch(url, opzioni);
  if (!r.ok) {
    let msg = `Errore ${r.status}`;
    try { msg = (await r.json()).detail || msg; } catch (e) { /* risposta non JSON */ }
    throw new Error(msg);
  }
  return r.json();
}

// ------------------------------------------------------------ NUOVO PROGETTO

function paginaNuovo() {
  mostra("#t-nuovo");
  // PASSO 1: solo il caricamento. Il programma riconosce da solo la foto 360 (2:1) e la piantina (PDF o altra immagine).
  // Cosa fare, stile e materiali si scelgono dopo, nei passi guidati.
  let foto = null, piantina = null, fotoOk = false;
  const zona = $("#zona-upload"), input = $("#file"), avanti = $("#genera");

  function aggiorna() {
    const haFoto = !!(foto && fotoOk), haPiantina = !!piantina;
    $("#ok-foto").classList.toggle("fatto", haFoto);
    $("#ok-piantina").classList.toggle("fatto", haPiantina);
    $("#passo-stanza").hidden = !(haPiantina && haFoto);
    $("#nota-stanza").textContent = haFoto
      ? "Claude legge le misure di questa stanza: servono a dare le misure vere alla foto (circa 0,02 €)."
      : "Claude legge misure, porte e finestre di questa stanza e il programma la costruisce in scala (circa 0,02 €).";
    avanti.disabled = !(haFoto || haPiantina);
    avanti.textContent = haPiantina && !haFoto ? "Avanti · leggi le stanze della piantina (circa 0,05 €) →"
      : haPiantina ? "Avanti · leggi la piantina (circa 0,02 €) →" : "Avanti →";
    zona.classList.toggle("compatta", !!(foto || piantina));
  }

  // riconoscimento dei file: PDF = piantina; immagine 2:1 = foto 360; altre immagini = piantina
  async function riconosci(file) {
    if (file.type === "application/pdf" || /\.pdf$/i.test(file.name)) return "piantina";
    try {
      const bmp = await createImageBitmap(file);
      const r = bmp.width / bmp.height;
      if (bmp.close) bmp.close();
      return Math.abs(r - 2) < 0.03 ? "foto" : "piantina";
    } catch (e) { return "piantina"; }
  }
  async function aggiungi(files) {
    for (const f of files || []) {
      if ((await riconosci(f)) === "foto") await scegliFoto(f); else scegliPiantina(f);
    }
    aggiorna();
  }

  async function scegliFoto(file) {
    foto = file; fotoOk = true;
    $("#slot-foto").hidden = false;
    $("#info-foto").innerHTML = `<span class="chip">Controllo la foto…</span>`;
    $("#messaggi-foto").innerHTML = "";
    // anteprima leggera (4096 px): un 12K è troppo per molte schede video
    try {
      const bmp = await createImageBitmap(file, { resizeWidth: 4096, resizeHeight: 2048, resizeQuality: "high" });
      const canvas = document.createElement("canvas");
      canvas.width = 4096; canvas.height = 2048;
      canvas.getContext("2d").drawImage(bmp, 0, 0);
      const blob = await new Promise((ok) => canvas.toBlob(ok, "image/jpeg", 0.9));
      $("#anteprima").innerHTML = "";
      viewer("anteprima", URL.createObjectURL(blob), { autoRotate: -2 });
    } catch (e) {
      $("#anteprima").innerHTML = `<div class="vuoto">Anteprima non disponibile</div>`;
    }
    // controllo sul server: proporzioni e metadati 360
    const dati = new FormData(); dati.append("foto", file);
    try {
      const info = await api("/api/controlla-foto", { method: "POST", body: dati });
      const chips = [];
      if (info.larghezza) chips.push(`<span class="chip">${info.larghezza} × ${info.altezza}</span>`);
      chips.push(info.metadati_360 ? `<span class="chip ok">✓ Metadati 360</span>` : `<span class="chip">Senza metadati 360</span>`);
      if (info.fotocamera) chips.push(`<span class="chip">${info.fotocamera}</span>`);
      $("#info-foto").innerHTML = chips.join("");
      $("#messaggi-foto").innerHTML = (info.messaggi || []).map((m) => `<li class="${info.ok ? "" : "grave"}">${m}</li>`).join("");
      fotoOk = !!info.ok;
    } catch (e) {
      $("#info-foto").innerHTML = `<span class="chip">${file.name}</span>`;
    }
    aggiorna();
  }
  function scegliPiantina(file) {
    piantina = file;
    $("#slot-piantina").hidden = false;
    $("#info-piantina").innerHTML = `<span class="chip ok">${file.name}</span>`;
    $("#piantina-anteprima").innerHTML = file.type === "application/pdf"
      ? `<div class="vuoto">📄 PDF pronto: lo legge Claude</div>`
      : `<img src="${URL.createObjectURL(file)}" alt="Piantina">`;
  }

  input.addEventListener("change", () => { aggiungi([...input.files]); input.value = ""; });
  ["dragenter", "dragover"].forEach((ev) => zona.addEventListener(ev, (e) => { e.preventDefault(); zona.classList.add("sopra"); }));
  ["dragleave", "drop"].forEach((ev) => zona.addEventListener(ev, (e) => { e.preventDefault(); zona.classList.remove("sopra"); }));
  zona.addEventListener("drop", (e) => aggiungi([...e.dataTransfer.files]));
  $("#togli-foto").onclick = () => { pulisci(); foto = null; fotoOk = false; $("#slot-foto").hidden = true; aggiorna(); };
  $("#togli-piantina").onclick = () => { piantina = null; $("#slot-piantina").hidden = true; aggiorna(); };

  $("#modulo").addEventListener("submit", async (e) => {
    e.preventDefault();
    const conFoto = !!(foto && fotoOk);
    if (!conFoto && !piantina) return;
    if (piantina && conFoto && !$("#nome-stanza").value.trim()) {
      $("#nome-stanza").focus();
      $("#errore-modulo").textContent = "Scrivi quale stanza della piantina vuoi (es. camera matrimoniale).";
      $("#errore-modulo").hidden = false; return;
    }
    if (piantina && !(await chiediConferma("Faccio leggere la piantina a Claude?",
      conFoto ? "Claude legge le misure della stanza: il programma le usa per dare la scala giusta alla foto 360. Costo circa 0,02 €."
        : "Claude trova tutte le stanze della piantina con misure, porte e finestre; poi scegli quali lavorare. Costo circa 0,05 €.",
      "Leggi"))) return;
    avanti.disabled = true; avanti.textContent = "Caricamento…";
    $("#errore-modulo").hidden = true;
    const dati = new FormData();
    if (piantina) { dati.append("piantina", piantina); dati.append("stanza", $("#nome-stanza").value.trim()); }
    try {
      let r;
      if (conFoto) { dati.append("foto", foto); r = await api("/api/progetti", { method: "POST", body: dati }); }
      else {
        const casa = new FormData(); casa.append("piantina", piantina);
        const c = await api("/api/case", { method: "POST", body: casa });
        location.hash = `#/casa/${c.id}`;
        return;
      }
      location.hash = `#/rilievo/${r.id}`;
    } catch (err) {
      $("#errore-modulo").textContent = err.message; $("#errore-modulo").hidden = false;
      aggiorna();
    }
  });
  aggiorna();
}

// ------------------------------------------------------------ LAVORAZIONE

function paginaLavoro(id) {
  mostra("#t-lavoro");
  const chiavi = Object.keys(FASI);
  $("#fasi").innerHTML = chiavi.map((k, i) => `<li data-fase="${k}"><span class="pallino">${i + 1}</span>${FASI[k]}</li>`).join("");
  let avvio = Date.now() / 1000;

  async function aggiorna() {
    let d;
    try { d = await api(`/api/progetti/${id}`); } catch (e) { return; }
    $("#lavoro-richiesta").textContent = `“${d.richiesta}”`;
    const st = d.stato || {};
    if (st.stato === "finito") { location.hash = `#/progetto/${id}`; return; }
    if (st.stato === "mappa_pronta") { location.hash = `#/mappa/${id}`; return; }
    if (st.stato === "rilievo" || st.stato === "rilievo_confermato") { location.hash = `#/rilievo/${id}`; return; }
    if (st.stato === "errore") {
      $("#lavoro-testo").textContent = "Il lavoro si è fermato";
      $(".spinner-grande").style.animation = "none";
      const box = $("#lavoro-errore");
      box.hidden = false;
      box.textContent = `${st.testo || "Errore"}\n\n${d.errore_dettaglio ? "Dettagli tecnici:\n" + d.errore_dettaglio : ""}`;
      timerAttivi.forEach(clearInterval);
      return;
    }
    const indice = chiavi.indexOf(st.fase);
    document.querySelectorAll("#fasi li").forEach((li, i) => {
      li.classList.toggle("fatta", i < indice);
      li.classList.toggle("corrente", i === indice);
      li.querySelector(".pallino").textContent = i < indice ? "✓" : i + 1;
    });
    $("#lavoro-testo").textContent = st.testo || "In corso…";
    $("#lavoro-costo").textContent = euro(d.costo_euro);
    if (st.avvio) avvio = st.avvio;
  }
  timerAttivi.push(setInterval(() => { $("#lavoro-tempo").textContent = durata(Date.now() / 1000 - avvio); }, 1000));
  timerAttivi.push(setInterval(aggiorna, 1500));
  aggiorna();
}

// ------------------------------------------------------------ RILIEVO (SENZA AI)

async function paginaRilievo(id) {
  // rilievo automatico ancora in corso: attesa con avanzamento, poi la pagina si ricarica da sola
  const dettaglio = await api(`/api/progetti/${id}`);
  const stato = dettaglio.stato || {};
  const servizio = dettaglio.servizio || "rinnova";
  if (stato.stato === "in_corso" && (stato.fase === "rilievo_auto" || stato.fase === "svuota")) {
    pulisci();
    const svuoto = stato.fase === "svuota";
    pagina.innerHTML = `<section class="intestazione"><h1>${svuoto ? "Svuoto la stanza…" : "Misuro la stanza…"}</h1>
      <p>${svuoto ? "ChatGPT toglie mobili e oggetti, poi il programma misura la stanza vuota. Circa 1-2 minuti."
        : "Il programma trova pareti, pavimento e soffitto in automatico. Ci vogliono pochi secondi."}</p></section>
      <div class="pannello stato-live"><div class="spinner-grande"></div><div class="testo-live">${stato.testo || ""}</div></div>`;
    timerAttivi.push(setInterval(async () => {
      const st = (await api(`/api/progetti/${id}`)).stato || {};
      if (st.stato !== "in_corso") naviga();
    }, 1500));
    return;
  }
  mostra("#t-rilievo");
  if (dettaglio.casa) {
    const barra = document.createElement("nav");
    barra.className = "casa-barra";
    barra.innerHTML = `<span class="etichetta-piccola">🏠 Stanze della casa</span>` +
      (dettaglio.casa_stanze || []).map((s) => `<a href="#/rilievo/${s.id}" class="${s.id === id ? "attivo" : ""}">${s.nome}</a>`).join("") +
      `<a href="#/casa/${dettaglio.casa}" class="altre">+ altre stanze</a>`;
    $("#r-passi").before(barra);
  }
  const NOMI_SERVIZI = { rinnova: "Ristruttura", prodotto: "Prova prodotto", riprogetta: "Progetta", arreda: "Progetta" };
  const conVarianti = servizio === "riprogetta" || servizio === "arreda";
  $("#r-servizio").textContent = dettaglio.servizio_scelto === false && dettaglio.origine !== "piantina"
    ? "Nuovo progetto" : NOMI_SERVIZI[servizio];
  // Modo tecnico (rilievo a mano, radar, punti): solo per noi, aprendo la pagina con ?avanzati nell'indirizzo.
  // Il cliente non lo vede mai.
  const modoTecnico = new URLSearchParams(location.search).has("avanzati");
  document.body.classList.toggle("mostra-avanzati", modoTecnico);
  // ogni servizio: titolo, spiegazione in passi semplici e solo i pannelli che servono
  const TESTI = {
    rinnova: ["Ristrutturazione della stanza", "Stessi mobili, stessa stanza: tutto rifatto come hai chiesto.",
      "Se vuoi, aggiungi qui sotto le foto dei materiali veri (pavimento, pareti…). Poi premi Genera."],
    prodotto: ["Cosa vuoi provare nella stanza", "Cambia SOLO quello che chiedi: il resto della foto resta identico al pixel.",
      "1) Carica la foto del prodotto. 2) Scrivi cosa vuoi fare (es. «sostituisci il letto con questo»): "
      + "il programma trova da solo il punto nella foto. 3) Premi Prova nella stanza. "
      + "Puoi provare anche un materiale (pavimento, pareti…) con le schede qui sotto."],
    riprogetta: ["Nuova disposizione", "Nuova disposizione dei mobili, con più varianti da confrontare.",
      "1) Premi ✨ Proponi arredo oppure aggiungi i mobili con i pulsanti e clicca sul pavimento dove vanno. "
      + "2) Se vuoi, trascina le foto dei prodotti veri sulle schede. 3) Genera la variante; puoi crearne altre (A, B, C)."],
    arreda: ["Dove vanno le cose", "Nuova disposizione a misura: l'arredo è progettato sulle misure vere della stanza.",
      "0) Se la stanza è arredata, premi 🧹 Svuota la stanza. 1) Premi ✨ Proponi arredo (Claude sceglie mobili e misure adatte allo spazio) "
      + "oppure aggiungi tu i mobili con i pulsanti e clicca sul pavimento dove vanno. "
      + "2) Se vuoi, trascina le foto dei prodotti veri sulle schede. 3) Premi Genera."],
  };
  const [titoloArredo, intro, passi] = TESTI[servizio] || TESTI.rinnova;
  $("#r-arredo-titolo").textContent = titoloArredo;
  $("#r-intro").textContent = intro;
  $("#r-arredo-testo").textContent = passi;
  // l'elenco mobili con le misure serve solo dove si dispongono i mobili
  $("#r-pannello-mobili").closest(".colonna").hidden = !(servizio === "arreda" || servizio === "riprogetta") && !modoTecnico;
  $(".griglia-consegna").classList.toggle("senza-colonna", !(servizio === "arreda" || servizio === "riprogetta") && !modoTecnico);
  const [salvato, preset] = await Promise.all([api(`/api/progetti/${id}/stanza`), api("/api/presets-rilievo")]);
  const dati = Object.assign({ altezza_camera: 1.5, inclinazione: { pitch: 0, roll: 0 }, angoli: [], spigoli: [],
    pareti: {}, soffitto: null, fissi: [], mobili: [] }, salvato.input || {});
  if (servizio === "prodotto" && !(dati.prodotti && dati.prodotti.length)) dati.prodotti = [{ nome: "Prodotto 1", istruzione: "" }];
  if (conVarianti) {
    dati.varianti = dati.varianti || { A: dati.mobili };
    dati.variante = dati.variante && dati.varianti[dati.variante] ? dati.variante : Object.keys(dati.varianti)[0];
    dati.mobili = dati.varianti[dati.variante];
  }
  let stanzaAffidabile = true;   // false se il rilievo automatico ha sbagliato la stanza
  let daCatalogo = null;         // prodotto del catalogo scelto, in attesa del clic sul pavimento
  let haAnteprima = false;       // c'è già un'anteprima 3D di questa visita alla pagina
  let superfici = dettaglio.superfici || {};
  let tipoStanza = dettaglio.tipo_stanza || "altro";
  const NOMI_STANZA = { bagno: "Bagno", cucina: "Cucina", camera: "Camera", soggiorno: "Soggiorno", altro: "Altra stanza" };
  // categorie del catalogo che hanno senso in ogni stanza (altro = tutte)
  const CATEGORIE_STANZA = {
    bagno: ["Sanitari", "Doccia", "Vasca", "Mobile bagno", "Specchio", "Rubinetteria", "Termoarredo", "Illuminazione", "Arredo", "Altro"],
    cucina: ["Cucina", "Tavolo", "Sedia", "Illuminazione", "Arredo", "Altro"],
    camera: ["Letto", "Armadio", "Specchio", "Arredo", "Illuminazione", "Altro"],
    soggiorno: ["Divano", "Tavolo", "Sedia", "Specchio", "Arredo", "Illuminazione", "Altro"],
  };
  let piastrelleCatalogo = null;
  const ZONE_SUP = [
    ["pavimento", "Pavimento", false, false], ["rivestimento", "Rivestimento pareti", true, false],
    ["zona_lavabo", "Dietro il lavabo", true, false], ["zona_vasca", "Dietro la vasca", true, false],
    ["doccia", "Zona doccia", true, false], ["pareti", "Pareti (tutte, sopra il rivestimento)", false, true],
    ["parete_fondo", "Solo parete A", true, true], ["parete_destra", "Solo parete B", true, true],
    ["parete_dietro", "Solo parete C", true, true], ["parete_sinistra", "Solo parete D", true, true],
    ["soffitto", "Soffitto", false, true],
  ];
  const ALTEZZA_BASE = { rivestimento: 120, doccia: 220, zona_vasca: 220, zona_lavabo: 120 };

  // ANTEPRIMA 3D: lo stesso motore del 360 finale, a bassa risoluzione, per vedere i prodotti veri al loro posto
  async function faiAnteprima() {
    const attesa = $("#r-attesa");
    attesa.hidden = false;
    attesa.lastChild.textContent = "Blender prepara l'anteprima 3D…";
    try {
      await salva(false, true);
      const r = await api(`/api/progetti/${id}/anteprima3d`, { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ variante: dati.variante || null }) });
      haAnteprima = true;
      mostra360DaPiantina();
      await cambiaVista("anteprima");
      $("#r-contenitore").scrollIntoView({ behavior: "smooth", block: "center" });
      disegnaAzioni();
      mostraMessaggio(`Anteprima pronta in ${Math.round(r.secondi)} secondi. Il 360 finale sarà in alta risoluzione.`, "ok");
    } catch (e) { mostraMessaggio(e.message); }
    finally { attesa.hidden = true; attesa.lastChild.textContent = "Un attimo…"; }
  }
  // progetti da piantina: niente modellino 3D a blocchi mentre si progetta. Si lavora sulla piantina dall'alto;
  // il 360 compare solo con l'anteprima vera (render Blender), quando la si chiede, e nel render finale.
  function mostra360DaPiantina() {
    const vedi = haAnteprima && (passo === "disposizione" || passo === "stile");
    ["#r-contenitore", "#r-barra"].forEach((sel) => $(sel) && $(sel).classList.toggle("fuori-passo", !vedi));
    $("#r-viste").hidden = true;
    if (vedi && vistaCorrente !== "anteprima") cambiaVista("anteprima");
  }
  // CARICAMENTO SEMPRE VISIBILE: la rotellina "Un attimo…" sta dentro il riquadro del 360; quando il 360 è nascosto
  // (progetti da piantina) si mostra al suo posto una finestra in mezzo allo schermo con lo stesso testo
  const attesaVisibile = document.createElement("div");
  attesaVisibile.className = "attesa-schermo";
  attesaVisibile.hidden = true;
  attesaVisibile.innerHTML = `<div class="attesa-scheda"><div class="spinner-grande"></div><strong></strong>
    <span class="sottile">Non chiudere la pagina: ci vuole poco.</span></div>`;
  document.body.appendChild(attesaVisibile);
  // cambiando pagina (es. dopo Genera si passa a "Sto lavorando") la finestra di attesa se ne va con la pagina
  window.addEventListener("hashchange", () => { attesaVisibile.remove(); osservaAttesa.disconnect(); }, { once: true });
  const allineaAttesa = () => {
    const a = $("#r-attesa");
    if (!a || !document.body.contains(a)) { attesaVisibile.remove(); osservaAttesa.disconnect(); return; }
    const nascosto360 = !$("#r-contenitore").offsetParent;
    attesaVisibile.hidden = a.hidden || !nascosto360;
    attesaVisibile.querySelector("strong").textContent = a.lastChild.textContent.trim() || "Un attimo…";
  };
  const osservaAttesa = new MutationObserver(allineaAttesa);
  osservaAttesa.observe($("#r-attesa"), { attributes: true, childList: true, characterData: true, subtree: true });
  let maniglie360 = false;       // passo "La stanza" (foto): pallini sulle linee gialle per spostare le pareti nel 360
  let disegnaSvg = () => {};     // piantina 2D (solo progetti da piantina): si ridisegna a ogni salvataggio
  let modo = "naviga", vistaCorrente = "foto", provvisorio = null, vista = null, timer = null, hotspot = [];
  const file = (n) => `/api/progetti/${id}/file/${n}?v=${Date.now()}`;

  // menu dei tipi di elementi fissi e di mobili
  $("#r-tipo-fisso").innerHTML = preset.fissi.map((t) => `<option value="${t}">${t}</option>`).join("");
  $("#r-tipo-mobile").innerHTML = Object.entries(preset.mobili).map(([n, m]) =>
    `<option value="${n}">${n} ${m.forma === "cilindro" ? "Ø" + m.larghezza : m.larghezza + "×" + m.profondita}</option>`).join("");
  $("#r-altezza").value = dati.altezza_camera;
  $("#r-tara").checked = dati.tara_porta !== false;
  $("#r-alt-porta").value = Math.round((dati.altezza_porta || 2.1) * 100);
  $("#r-pitch").value = dati.inclinazione.pitch;
  $("#r-roll").value = dati.inclinazione.roll;

  const suggerimenti = {
    naviga: "Trascina per guardarti intorno.",
    angoli: "Clicca gli angoli VISIBILI dove due pareti toccano il PAVIMENTO. Se un angolo è coperto, usa Spigoli e Battiscopa.",
    spigoli: "Clicca un punto qualsiasi dello SPIGOLO verticale tra due pareti (anche in alto, sopra i mobili). Uno per angolo.",
    battiscopa: "Scegli la parete (A, B, C, D) e clicca 2 o più punti sulla linea parete-pavimento dove si vede. Poi passa alla parete successiva.",
    soffitto: "Clicca UN angolo dove due pareti toccano il SOFFITTO (serve per l'altezza).",
    fissi: "Scegli il tipo, poi clicca due angoli opposti dell'elemento (es. in alto a sinistra e in basso a destra).",
    mobili: "Scegli il mobile, poi clicca sul pavimento dove va. Le misure si cambiano nell'elenco a destra.",
    cancella: "Clicca su un punto sbagliato (anche quelli trovati in automatico) per toglierlo.",
    linee: "Trascina le maniglie: tonde = angoli a terra, quadrate = centro di una parete, verde = soffitto. La guida si ridisegna da sola.",
  };

  let inquadraturaLarga = false;   // passo "La stanza": si guarda un po' in basso con un campo largo (linee e pallini visibili)
  function caricaViewer() {
    let pos = vista && vista.isLoaded() ? { yaw: vista.getYaw(), pitch: vista.getPitch(), hfov: vista.getHfov() } : {};
    if (inquadraturaLarga) { pos = { yaw: pos.yaw || 0, pitch: -28, hfov: 120 }; inquadraturaLarga = false; }
    if (vista) { try { vista.destroy(); } catch (e) { /* già chiuso */ } viewerAttivi = viewerAttivi.filter((v) => v !== vista); }
    const img = { foto: "viewer_prima.jpg", guida: "guida_controllo.jpg", linee: "viewer_prima.jpg",
      anteprima: "anteprima3d.jpg" }[vistaCorrente];
    vista = viewer("v-rilievo", file(img), pos);
    hotspot = [];
    vista.on("load", disegnaPunti);
  }

  function punto(idh, yaw, pitch, testo, classe) {
    vista.addHotSpot({ id: idh, yaw, pitch, cssClass: `hs-punto ${classe}`,
      createTooltipFunc: (div) => { div.textContent = testo; } });
    hotspot.push(idh);
  }

  function disegnaPunti() {
    if (!vista || !vista.isLoaded()) return;
    hotspot.forEach((h) => { try { vista.removeHotSpot(h); } catch (e) { /* assente */ } });
    hotspot = [];
    if (modoTecnico) {   // punti del rilievo: solo per noi
      dati.angoli.forEach((a, i) => punto(`a${i}`, a[0], a[1], i + 1, ""));
      dati.spigoli.forEach((a, i) => punto(`e${i}`, a[0], a[1] ?? 0, "|", "soffitto"));
      Object.entries(dati.pareti).forEach(([k, pts]) => pts.forEach((a, i) => punto(`b${k}${i}`, a[0], a[1], k, "mobile")));
      if (dati.soffitto) punto("s", dati.soffitto[0], dati.soffitto[1], "S", "soffitto");
      if (vistaCorrente === "foto")
        dati.fissi.forEach((f, i) => { punto(`f${i}a`, f.p1[0], f.p1[1], "F", "fisso"); punto(`f${i}b`, f.p2[0], f.p2[1], "F", "fisso"); });
    }
    // nomi delle pareti (A, B, C, D) sulla foto, per i materiali "solo questa parete"
    // (A = fondo, B = destra, C = dietro, D = sinistra, a 2 m da terra: come nella guida interna)
    const s = ultimaStanza;
    if ((vistaCorrente === "foto" || vistaCorrente === "linee") && s && stanzaAffidabile) {
      const yl = 2.0 - s.h;
      [["A", (s.XL + s.XR) / 2, s.ZW], ["B", s.XR, (s.ZB + s.ZW) / 2], ["C", (s.XL + s.XR) / 2, s.ZB], ["D", s.XL, (s.ZB + s.ZW) / 2]]
        .forEach(([lettera, X, Z]) => {
          const [yaw, pitch] = versoMondo(s, X, yl, Z);
          vista.addHotSpot({ id: `w${lettera}`, yaw, pitch, cssClass: "hs-etichetta parete",
            createTooltipFunc: (div) => { div.textContent = `Parete ${lettera}`; } });
          hotspot.push(`w${lettera}`);
        });
    }
    // i mobili si vedono come etichetta col nome, nel punto dove vanno
    if (vistaCorrente === "foto" && (servizio === "arreda" || servizio === "riprogetta" || modoTecnico)) {
      dati.mobili.forEach((m, i) => {
        // posizione: sopra il mobile calcolato nella stanza (vale anche per quelli proposti da Claude, che non hanno
        // un clic ma il centro in metri); se manca, il punto cliccato
        const sm = s && (s.mobili || [])[i];
        const pos = sm && sm.centro_m
          ? versoMondo(s, sm.centro_m[0], -s.h + (sm.quota_m || 0) + (sm.A || 0.5) + 0.1, sm.centro_m[1])
          : m.clic;
        if (!pos) return;
        vista.addHotSpot({ id: `m${i}`, yaw: pos[0], pitch: pos[1], cssClass: "hs-etichetta",
          createTooltipFunc: (div) => { div.textContent = m.nome; } });
        hotspot.push(`m${i}`);
      });
    }
    if (provvisorio) punto("p", provvisorio[0], provvisorio[1], "1° angolo", "provvisorio");
    if (modo === "linee" || maniglie360) disegnaManiglie(modo !== "linee");
  }

  // ---- maniglie per spostare le linee del radar (mouse o dito)
  let ultimaStanza = null, trascina = null;
  const gradi = (r) => r * 180 / Math.PI, rad = (g) => g * Math.PI / 180;
  function versoMondo(s, X, y, Z) {           // da coordinate stanza a yaw/pitch del viewer
    const c = Math.cos(s.theta), sn = Math.sin(s.theta);
    const x = c * X - sn * Z, z = sn * X + c * Z;
    return [gradi(Math.atan2(x, z)), gradi(Math.atan2(y, Math.hypot(x, z)))];
  }
  function versoStanza(s, yaw, pitch) {       // da yaw/pitch a direzione nel sistema della stanza
    const x = Math.cos(rad(pitch)) * Math.sin(rad(yaw)), y = Math.sin(rad(pitch)), z = Math.cos(rad(pitch)) * Math.cos(rad(yaw));
    const c = Math.cos(s.theta), sn = Math.sin(s.theta);
    return [c * x + sn * z, y, -sn * x + c * z];
  }
  function disegnaManiglie(soloPareti = false) {
    const s = ultimaStanza;
    if (!s || !vista || !vista.isLoaded()) return;
    const yp = -s.h, ys = s.H - s.h;
    const maniglie = [
      ["c_XL_ZB", s.XL, yp, s.ZB, ""], ["c_XR_ZB", s.XR, yp, s.ZB, ""], ["c_XR_ZW", s.XR, yp, s.ZW, ""], ["c_XL_ZW", s.XL, yp, s.ZW, ""],
      ["p_XL", s.XL, yp, (s.ZB + s.ZW) / 2, "parete"], ["p_XR", s.XR, yp, (s.ZB + s.ZW) / 2, "parete"],
      ["p_ZB", (s.XL + s.XR) / 2, yp, s.ZB, "parete"], ["p_ZW", (s.XL + s.XR) / 2, yp, s.ZW, "parete"],
      ["s_H", (s.XL + s.XR) / 2, ys, s.ZW, "soffitto"],
    ];
    // per il cliente solo un pallino a metà di ogni parete, sulla linea gialla a terra (gli angoli e il soffitto
    // restano negli strumenti tecnici)
    maniglie.filter(([chiave]) => !soloPareti || chiave.startsWith("p_")).forEach(([chiave, X, y, Z, classe]) => {
      if (soloPareti) classe = "guidata";
      const [yaw, pitch] = versoMondo(s, X, y, Z);
      vista.addHotSpot({ id: `h_${chiave}`, yaw, pitch, cssClass: `hs-maniglia ${classe}`,
        createTooltipFunc: (div) => {
          const inizia = (e) => {
            e.preventDefault(); e.stopPropagation();
            trascina = { chiave, fantasma: document.createElement("div") };
            trascina.fantasma.className = "fantasma";
            document.body.appendChild(trascina.fantasma);
            sposta(e);
          };
          ["pointerdown", "mousedown", "touchstart"].forEach((ev) => div.addEventListener(ev, inizia, { passive: false }));
        } });
      hotspot.push(`h_${chiave}`);
    });
  }
  function puntoEvento(e) { return e.touches ? e.touches[0] || e.changedTouches[0] : e; }
  function sposta(e) {
    if (!trascina) return;
    const p = puntoEvento(e);
    trascina.fantasma.style.left = `${p.clientX}px`; trascina.fantasma.style.top = `${p.clientY}px`;
    trascina.ultimo = p;
  }
  async function rilascia() {
    if (!trascina) return;
    const { chiave, fantasma, ultimo } = trascina;
    trascina = null; fantasma.remove();
    if (!ultimo || !ultimaStanza) return;
    const [pitch, yaw] = vista.mouseEventToCoords({ clientX: ultimo.clientX, clientY: ultimo.clientY });
    const s = { ...ultimaStanza };
    const d = versoStanza(s, yaw, pitch);
    if (chiave === "s_H") {                           // soffitto: dove il raggio incontra la parete di fondo
      if (d[2] <= 0.05 || d[1] <= 0) { avviso("Trascina la maniglia verde sullo spigolo parete-soffitto."); disegnaPunti(); return; }
      s.H = s.h + (s.ZW / d[2]) * d[1];
    } else {
      if (d[1] > -0.03) { avviso("Le maniglie a terra vanno sotto l'orizzonte: trascina più in basso."); disegnaPunti(); return; }
      const t = -s.h / d[1], X = t * d[0], Z = t * d[2];
      const [tipo, a, b] = chiave.split("_");
      if (tipo === "c") { s[a] = X; s[b] = Z; } else s[a] = a.startsWith("X") ? X : Z;
    }
    if (!(s.XL < -0.2 && s.XR > 0.2 && s.ZB < -0.2 && s.ZW > 0.2)) { avviso("Così la fotocamera resterebbe fuori dalla stanza."); disegnaPunti(); return; }
    dati.scatola = { h: s.h, theta: s.theta, XL: s.XL, XR: s.XR, ZB: s.ZB, ZW: s.ZW, H: s.H };
    dati.altezza_camera = s.h; $("#r-altezza").value = s.h;      // stessa scala di adesso
    delete dati.misura_vera;
    disegnaListe();
    await aggiornaGuida(true);
    if (vistaCorrente !== "foto") caricaViewer();                // linee gialle ridisegnate al nuovo posto
  }
  window.addEventListener("pointermove", sposta);
  window.addEventListener("touchmove", sposta, { passive: true });
  window.addEventListener("pointerup", rilascia);
  window.addEventListener("touchend", rilascia);

  // clic (non trascinamento) nel viewer
  const contenitore = $("#v-rilievo");
  let giu = null;
  contenitore.addEventListener("pointerdown", (e) => { giu = [e.clientX, e.clientY]; }, true);
  contenitore.addEventListener("pointerup", (e) => {
    if (!giu || modo === "naviga" || !vista || Math.hypot(e.clientX - giu[0], e.clientY - giu[1]) > 5) return;
    const [pitch, yaw] = vista.mouseEventToCoords(e);
    clic([+yaw.toFixed(3), +pitch.toFixed(3)]);
  }, true);

  function distanza(a, b) {
    const dy = ((a[0] - b[0] + 540) % 360) - 180;
    return Math.hypot(dy * Math.cos((a[1] ?? 0) * Math.PI / 180), (a[1] ?? 0) - (b[1] ?? a[1] ?? 0));
  }

  function cancellaVicino(yp) {
    // il punto più vicino al clic (entro 4°) viene tolto: angolo, spigolo, battiscopa, soffitto, elemento o mobile
    const candidati = [];
    dati.angoli.forEach((a, i) => candidati.push([distanza(yp, a), () => dati.angoli.splice(i, 1)]));
    dati.spigoli.forEach((a, i) => candidati.push([Math.abs(((yp[0] - a[0] + 540) % 360) - 180), () => dati.spigoli.splice(i, 1)]));
    Object.entries(dati.pareti).forEach(([k, pts]) => pts.forEach((a, i) => candidati.push([distanza(yp, a), () => pts.splice(i, 1)])));
    if (dati.soffitto) candidati.push([distanza(yp, dati.soffitto), () => { dati.soffitto = null; }]);
    dati.fissi.forEach((f, i) => candidati.push([Math.min(distanza(yp, f.p1), distanza(yp, f.p2)), () => dati.fissi.splice(i, 1)]));
    dati.mobili.forEach((m, i) => m.clic && candidati.push([distanza(yp, m.clic), () => dati.mobili.splice(i, 1)]));
    candidati.sort((x, y) => x[0] - y[0]);
    if (!candidati.length || candidati[0][0] > 4) { avviso("Nessun punto qui vicino: clicca proprio sopra il punto da togliere."); return false; }
    candidati[0][1]();
    return true;
  }

  function clic(yp, centro = null) {
    const dove = centro ? { centro } : { clic: yp };     // punto del 360 oppure punto della piantina
    if (modo === "cancella") {
      if (!cancellaVicino(yp)) return;
    } else if (modo === "linee") {
      return;
    } else if (modo === "angoli") {
      delete dati.scatola;
      if (yp[1] > -2) { avviso("Gli angoli del pavimento sono sotto l'orizzonte: clicca più in basso."); return; }
      dati.angoli.push(yp);
    } else if (modo === "spigoli") {
      delete dati.scatola;
      dati.spigoli.push(yp);
    } else if (modo === "battiscopa") {
      if (yp[1] > -2) { avviso("Il battiscopa è sotto l'orizzonte: clicca più in basso."); return; }
      const k = $("#r-parete").value;
      (dati.pareti[k] = dati.pareti[k] || []).push(yp);
    } else if (modo === "soffitto") {
      dati.soffitto = yp;
    } else if (modo === "fissi") {
      if (!provvisorio) { provvisorio = yp; disegnaPunti(); return; }
      const tipo = $("#r-tipo-fisso").value;
      const n = dati.fissi.filter((f) => f.tipo === tipo).length + 1;
      dati.fissi.push({ tipo, nome: `${tipo[0].toUpperCase()}${tipo.slice(1)}${n > 1 ? " " + n : ""}`, p1: provvisorio, p2: yp });
      provvisorio = null;
    } else if (modo === "mobili" && daCatalogo) {
      // prodotto del catalogo dell'impresa: misure vere della scheda + il suo modello 3D nel render
      const p = daCatalogo;
      daCatalogo = null;
      dati.mobili.push({ nome: p.nome, tipo: `${p.categoria} ${p.nome}`, larghezza: p.larghezza, profondita: p.profondita,
        altezza: p.altezza, quota: p.quota || (p.categoria === "Specchio" ? 105 : 0), forma: "box", muro: true, ...dove, rotazione: 0, catalogo: p.id });
      modo = "naviga";
      $("#r-contenitore").style.cursor = "";
      document.querySelectorAll("[data-catalogo]").forEach((x) => x.classList.remove("attivo"));
      mostraMessaggio(`${p.nome} aggiunto. Spostalo trascinandolo nella piantina; per toglierlo usa 🗑 nell'elenco a destra.`, "ok");
    } else if (modo === "mobili") {
      const tipo = $("#r-tipo-mobile").value;
      // nomi unici (Comodino, Comodino 2…) così ogni mobile ha le sue foto prodotto
      const uguali = dati.mobili.filter((m) => (m.tipo || m.nome) === tipo).length;
      const nome = uguali ? `${tipo} ${uguali + 1}` : tipo;
      dati.mobili.push({ nome, tipo, ...preset.mobili[tipo], ...dove, rotazione: 0 });
      // un clic = un mobile: poi si torna a guardare (niente mobili doppi con clic ripetuti)
      modo = "naviga";
      $("#r-contenitore").style.cursor = "";
      document.querySelectorAll("[data-rapido]").forEach((x) => x.classList.remove("attivo"));
      mostraMessaggio(`${nome} aggiunto. Spostalo trascinandolo nella piantina; per toglierlo usa 🗑 nell'elenco a destra.`, "ok");
    }
    disegnaPunti(); disegnaListe(); salva();
    if (centro) aggiornaModello();
  }

  function avviso(testo) {
    mostraMessaggio(testo);
    $("#r-suggerimento").textContent = testo;
    setTimeout(() => { $("#r-suggerimento").textContent = suggerimenti[modo]; }, 3500);
  }

  function disegnaListe() {
    if (typeof disegnaRiferimenti === "function" && document.querySelector("#r-schede")) setTimeout(disegnaRiferimenti, 0);
    const nPareti = Object.values(dati.pareti).filter((p) => p.length >= 2).length;
    const parti = [];
    if (dati.angoli.length) parti.push(`${dati.angoli.length} angoli a terra`);
    if (dati.spigoli.length) parti.push(`${dati.spigoli.length} spigoli`);
    if (nPareti) parti.push(`battiscopa su ${nPareti} paret${nPareti === 1 ? "e" : "i"}`);
    if (dati.soffitto) parti.push("soffitto");
    $("#r-angoli").textContent = parti.join(" · ") || "Nessuno";
    $("#r-fissi").innerHTML = dati.fissi.map((f, i) =>
      `<li><span>${f.nome}</span><button class="link x" data-f="${i}">rimuovi</button></li>`).join("") || `<li class="sottile">Nessuno</li>`;
    $("#r-mobili").innerHTML = dati.mobili.map((m, i) => `<li data-m="${i}">
        <strong>${m.nome}</strong>
        <input type="number" data-k="larghezza" value="${m.larghezza}" title="larghezza">×
        <input type="number" data-k="profondita" value="${m.profondita}" title="profondità">h
        <input type="number" data-k="altezza" value="${m.altezza}" title="altezza">
        <span class="sottile">da terra</span><input type="number" data-k="quota" value="${m.quota || 0}" title="altezza da terra (cm)">
        <select data-k="rotazione" ${m.muro ? "disabled" : ""}>${[0, 90, 180, 270].map((r) =>
          `<option ${+m.rotazione === r ? "selected" : ""}>${r}</option>`).join("")}</select>
        <label class="sottile"><input type="checkbox" data-k="muro" ${m.muro ? "checked" : ""} style="width:auto"> al muro</label>
        <button class="clip ${contaRif(m.nome) ? "con" : ""}" data-clip="${i}" type="button" title="Allega foto del prodotto vero">📎 ${contaRif(m.nome) || "foto"}</button>
        <button type="button" class="togli-mobile" data-x="${i}" title="Togli questo mobile">🗑 Togli</button></li>`).join("") || `<li class="sottile">Nessuno</li>`;
    document.querySelectorAll("#r-fissi [data-f]").forEach((b) => b.onclick = () => {
      dati.fissi.splice(+b.dataset.f, 1); disegnaListe(); disegnaPunti(); salva(); });
    document.querySelectorAll("#r-mobili [data-clip]").forEach((b) => b.onclick = () =>
      scegliFotoRif("mobile", dati.mobili[+b.dataset.clip].nome));
    document.querySelectorAll("#r-mobili [data-x]").forEach((b) => b.onclick = () => {
      dati.mobili.splice(+b.dataset.x, 1); disegnaListe(); disegnaPunti(); salva(); });
    document.querySelectorAll("#r-mobili [data-k]").forEach((inp) => inp.onchange = () => {
      const m = dati.mobili[+inp.closest("li").dataset.m];
      m[inp.dataset.k] = inp.type === "checkbox" ? inp.checked : +inp.value;
      disegnaListe(); salva();
    });
  }

  // ---- prodotti reali e materiali (foto allegate)
  let riferimenti = (await api(`/api/progetti/${id}/riferimenti`)).riferimenti;
  if (servizio === "prodotto") {
    // foto prodotto caricate prima (es. "Oggetto 1" della vecchia selezione): diventano prodotti, non si perdono
    const nomi = [...new Set(riferimenti.filter((r) => r.destinazione === "mobile").map((r) => r.mobile))]
      .filter((n) => n && !dati.prodotti.some((x) => x.nome === n));
    const vuoto = (x) => !(x.istruzione || "").trim() && !riferimenti.some((r) => r.destinazione === "mobile" && r.mobile === x.nome);
    if (nomi.length) dati.prodotti = dati.prodotti.filter((x) => !vuoto(x)).concat(nomi.map((n) => ({ nome: n, istruzione: "" })));
  }
  let destinazioneRif = null;
  function contaRif(nome) { return riferimenti.filter((r) => r.destinazione === "mobile" && r.mobile === nome).length; }
  function scegliFotoRif(destinazione, mobile = "") { destinazioneRif = { destinazione, mobile }; $("#r-file-rif").value = ""; $("#r-file-rif").click(); }
  function disegnaRiferimenti() {
    // schede grandi sotto il 360: una per mobile + tre per i materiali
    const miniature = (filtro) => riferimenti.filter(filtro).map((r) => `<figure>
        <img src="/api/progetti/${id}/riferimenti/${r.id}.jpg" alt="" title="${r.nome_file || ""}">
        <button type="button" data-togli="${r.id}" title="Togli">×</button></figure>`).join("");
    const notaDi = (filtro) => (riferimenti.find(filtro) || {}).nota || "";
    const primo = (filtro) => (riferimenti.find(filtro) || {}).id || "";
    const scheda = (titolo, sotto, dest, mobile = "") => {
      const filtro = (r) => r.destinazione === dest && (dest !== "mobile" || r.mobile === mobile);
      const id1 = primo(filtro);
      return `<div class="scheda-arredo">
        <div class="titolo"><strong>${titolo}</strong><span>${sotto}</span></div>
        <div class="zona-prodotto" data-dest="${dest}" data-mobile="${mobile}">📎 Trascina qui la foto<br>o clicca per sceglierla</div>
        <div class="miniature">${miniature(filtro)}</div>
        ${id1 ? `<input class="nota" data-nota="${id1}" value="${notaDi(filtro).replace(/"/g, "&quot;")}" placeholder="Nota: modello, colore, finitura">` : ""}
      </div>`;
    };
    // Prova prodotto: per ogni prodotto la foto e cosa farne, scritto a parole (la zona la trova il programma)
    const schedaProdotto = (x, i) => `<div class="scheda-prodotto">
        ${scheda(`📦 ${x.nome}`, "foto del prodotto (es. dal sito del produttore)", "mobile", x.nome)}
        <label class="cosa-fare">Cosa vuoi fare con questo prodotto?
          <textarea data-istr="${i}" rows="2" placeholder="Es. Sostituisci il letto con questo. Oppure: aggiungi questa poltrona nell'angolo vicino alla finestra.">${(x.istruzione || "").replace(/</g, "&lt;")}</textarea>
        </label>
        ${dati.prodotti.length > 1 ? `<button type="button" class="link x" data-togli-prodotto="${i}">togli questo prodotto</button>` : ""}
      </div>`;
    // Rinnova tiene i mobili dove sono: niente schede mobili, solo i materiali
    $("#r-schede").innerHTML = servizio === "rinnova" ? ""
      : servizio === "prodotto" ? dati.prodotti.map(schedaProdotto).join("")
      : dati.mobili.length
      ? dati.mobili.map((m) => scheda(m.nome, m.forma === "cilindro" ? `Ø${m.larghezza}` : `${m.larghezza}×${m.profondita} cm`, "mobile", m.nome)).join("")
      : `<div class="vuoto-arredo">Per allegare la foto di un mobile vero (es. il tuo letto): prima aggiungilo con i pulsanti qui sopra
          o con ✨ Proponi arredo, e comparirà qui la sua scheda dove trascinare la foto.</div>`;
    document.querySelectorAll("#r-schede [data-istr]").forEach((ta) => ta.oninput = () => {
      dati.prodotti[+ta.dataset.istr].istruzione = ta.value; salva();
    });
    document.querySelectorAll("#r-schede [data-togli-prodotto]").forEach((b) => b.onclick = () => {
      dati.prodotti.splice(+b.dataset.togliProdotto, 1); salva(); disegnaRiferimenti();
    });
    const altezzaRiv = (riferimenti.find((r) => r.destinazione === "rivestimento") || {}).altezza_cm || 120;
    $("#r-materiali").innerHTML = [
      ["Pavimento", "materiale, formato e posa", "pavimento"],
      ["Tutte le pareti", "colore, intonaco, carta", "pareti"],
      ["Parete A", "solo questa parete", "parete_fondo"], ["Parete B", "solo questa parete", "parete_destra"],
      ["Parete C", "solo questa parete", "parete_dietro"], ["Parete D", "solo questa parete", "parete_sinistra"],
      ["Rivestimento", `piastrelle fino a <select id="r-alt-riv">${[90, 120, 150, 220, 270].map((v) =>
        `<option ${v === altezzaRiv ? "selected" : ""} value="${v}">${v} cm</option>`).join("")}</select>`, "rivestimento"],
      ["Soffitto", "colore o controsoffitto", "soffitto"],
      ["Porte interne", "modello e finitura", "porte"],
      ["Moodboard", "stile e palette", "moodboard"],
    ].map(([t, sotto, d]) => scheda(t, sotto, d)).join("");
    $("#r-alt-riv")?.addEventListener("click", (e) => e.stopPropagation());
    document.querySelectorAll("#r-arredo [data-togli]").forEach((b) => b.onclick = async () => {
      riferimenti = (await api(`/api/progetti/${id}/riferimenti/${b.dataset.togli}`, { method: "DELETE" })).riferimenti;
      disegnaRiferimenti(); disegnaListe();
    });
    document.querySelectorAll("#r-arredo [data-nota]").forEach((inp) => inp.onchange = async () => {
      riferimenti = (await api(`/api/progetti/${id}/riferimenti/${inp.dataset.nota}/nota`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ nota: inp.value }) })).riferimenti;
    });
    document.querySelectorAll("#r-arredo .zona-prodotto").forEach((z) => {
      z.onclick = () => scegliFotoRif(z.dataset.dest, z.dataset.mobile);
      ["dragenter", "dragover"].forEach((ev) => z.addEventListener(ev, (e) => { e.preventDefault(); z.classList.add("sopra"); }));
      ["dragleave", "drop"].forEach((ev) => z.addEventListener(ev, (e) => { e.preventDefault(); z.classList.remove("sopra"); }));
      z.addEventListener("drop", (e) => { const f = e.dataTransfer.files[0]; if (f) caricaRif(f, z.dataset.dest, z.dataset.mobile); });
    });
  }

  async function caricaRif(f, destinazione, mobile = "") {
    const corpo = new FormData();
    corpo.append("foto", f); corpo.append("destinazione", destinazione); corpo.append("mobile", mobile);
    if (destinazione === "rivestimento") corpo.append("altezza_cm", $("#r-alt-riv")?.value || 120);
    try {
      riferimenti = (await api(`/api/progetti/${id}/riferimenti`, { method: "POST", body: corpo })).riferimenti;
      disegnaRiferimenti(); disegnaListe();
    } catch (e) { avviso(e.message); }
  }

  // ---- azioni speciali del servizio
  function disegnaAzioni() {
    const box = $("#r-azioni-arredo");
    if (conVarianti) {
      // stanza arredata (foto 360): prima si svuota, poi si progetta l'arredo nuovo sulla stanza vuota
      const svuota = dettaglio.origine !== "piantina"
        ? (dettaglio.svuotata
          ? `<span class="chip ok">✓ Stanza svuotata</span><button type="button" class="link piccolo" id="r-svuota">rifai lo svuotamento</button>`
          : `<button type="button" class="bottone" id="r-svuota">🧹 Svuota la stanza · circa 0,15 €</button>`)
        : "";
      // progetti da piantina (motore 3D): anteprima del render con i prodotti veri, in pochi secondi e gratis
      const conAnteprima = dettaglio.origine === "piantina" && !!dati.pianta;
      box.innerHTML = `${svuota}${conAnteprima ? "" : `<button type="button" class="bottone magico" id="r-proponi">✨ Proponi arredo con Claude · circa 0,10 €</button>`}` +
        (conAnteprima ? `<button type="button" class="bottone" id="r-anteprima">👁 ${haAnteprima ? "Aggiorna l'anteprima 3D" : "Anteprima 3D"} · pochi secondi</button>` : "");
      if ($("#r-proponi")) $("#r-proponi").onclick = proponiArredo;
      if ($("#r-anteprima")) $("#r-anteprima").onclick = faiAnteprima;
      if ($("#r-svuota")) $("#r-svuota").onclick = async () => {
        if (!(await chiediConferma("Svuoto la stanza con ChatGPT?",
          "Toglie mobili e oggetti e tiene pareti, pavimento, porte e finestre. La stanza vuota diventa la base " +
          "su cui scegliere il nuovo arredo; la foto originale resta salvata. Costo circa 0,10–0,25 €.", "Svuota"))) return;
        try {
          await api(`/api/progetti/${id}/svuota`, { method: "POST" });
          naviga();
        } catch (e) { avviso(e.message); }
      };
    } else if (servizio === "prodotto") {
      box.innerHTML = `<button type="button" class="bottone" id="r-altro-prodotto">+ Aggiungi un altro prodotto</button>`;
      $("#r-altro-prodotto").onclick = () => {
        const usati = new Set(dati.prodotti.map((x) => x.nome));
        let n = dati.prodotti.length + 1;
        while (usati.has(`Prodotto ${n}`)) n++;
        dati.prodotti.push({ nome: `Prodotto ${n}`, istruzione: "" });
        salva(); disegnaRiferimenti();
      };
    }
  }
  async function proponiArredo() {
    if (!(await chiediConferma("Faccio progettare l'arredo a Claude?",
      `Claude calcola posizione e misura di ogni mobile sulla stanza vera (variante ${dati.variante}). Costo circa 0,05–0,15 €.`, "Proponi"))) return;
    $("#r-attesa").hidden = false;
    $("#r-attesa").lastChild.textContent = "Claude sta progettando l'arredo…";
    try {
      await salva(true);
      const r = await api(`/api/progetti/${id}/proponi-arredo`, { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ variante: dati.variante }) });
      dati.mobili = r.mobili; dati.varianti[dati.variante] = r.mobili;
      const box = $("#r-proposta");
      box.hidden = false;
      box.innerHTML = `<strong>Proposta di Claude (variante ${dati.variante})</strong><div>${r.ragionamento}</div>` +
        (r.problemi.length ? `<ul>${r.problemi.map((x) => `<li>${x}</li>`).join("")}</ul>` : `<div class="sottile">✓ Verificata: nessuna sovrapposizione, porte libere.</div>`);
      disegnaListe(); disegnaPunti();
      await aggiornaGuida(true);
    } catch (e) { avviso(e.message); } finally { $("#r-attesa").hidden = true; $("#r-attesa").lastChild.textContent = "Disegno la guida…"; }
  }
  disegnaAzioni();

  function dovePosare(nome) {
    if (daPiantina) {
      mostraMessaggio(`Ora clicca nella piantina il punto dove va: ${nome}. Poi puoi trascinarlo.`, "ok");
      $("#r-pianta").scrollIntoView({ behavior: "smooth", block: "center" });
    } else {
      $("#r-suggerimento").textContent = `Ora clicca sul pavimento del 360 dove va: ${nome}.`;
      document.querySelector("#r-contenitore").scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }

  // pulsanti rapidi per aggiungere i mobili più usati
  const rapidi = ["Letto matrimoniale", "Letto singolo", "Comodino", "Armadio", "Divano", "Poltrona", "Tavolo rettangolare", "Tavolo tondo",
    "Sedia", "Basi cucina", "Mobile bagno", "Doccia", "WC sospeso", "Bidet sospeso", "Vasca", "Termoarredo", "Tappeto"];
  // i pulsanti dei mobili generici servono solo in Arreda da foto: nei progetti 3D si usano solo i pezzi del catalogo
  $("#r-rapidi").hidden = !conVarianti || (dettaglio.origine === "piantina" && !!dati.pianta);
  // prodotti del catalogo dell'impresa: un clic sul prodotto, poi un clic sul pavimento del 360 dove va
  api("/api/catalogo").then((c) => {
    // le misure cambiate nel Catalogo valgono anche per i prodotti già messi in questo progetto
    let cambiati = 0;
    Object.values(dati.varianti || { A: dati.mobili }).forEach((lista) => (lista || []).forEach((m) => {
      const p = m.catalogo && c.prodotti.find((x) => x.id === m.catalogo);
      if (!p) return;
      ["larghezza", "profondita", "altezza", "quota"].forEach((k) => {
        if (p[k] != null && +m[k] !== +p[k]) { m[k] = +p[k]; cambiati++; }
      });
    }));
    if (cambiati) { disegnaListe(); aggiornaModello(); mostraMessaggio("Misure aggiornate dal Catalogo.", "ok"); }
    catalogoProdotti = c.prodotti;
    disegnaCatalogoRilievo();
  }).catch(() => {});
  let catalogoProdotti = [];
  // i pezzi del catalogo per QUESTA stanza (in un bagno: sanitari, docce, vasche, mobili bagno…)
  function disegnaCatalogoRilievo() {
    const box = $("#r-catalogo-rilievo"), c = { prodotti: catalogoProdotti };
    if (!box) return;
    const da3d = dettaglio.origine === "piantina" && !!dati.pianta;
    const adatte = CATEGORIE_STANZA[tipoStanza];
    const prodotti = c.prodotti.filter((p) => p.tipo !== "piastrella" && !(p.categoria === "Illuminazione" && (p.tipo_luce || "faretto") !== "applique")
      && (!adatte || adatte.includes(p.categoria)));
    box.hidden = !conVarianti || (!prodotti.length && !da3d);
    box.innerHTML = `<span class="etichetta-piccola">📦 ${da3d ? `I pezzi del tuo catalogo per: ${NOMI_STANZA[tipoStanza]}` : "Dal mio catalogo"}</span>` +
      (prodotti.length ? prodotti.map((p) =>
        `<button type="button" data-catalogo="${p.id}" title="${p.larghezza}×${p.profondita}×h${p.altezza} cm">${p.stato_modello === "pronto" ? "🧊 " : ""}${p.nome}</button>`).join("")
        : `<span class="sottile">Nessun pezzo per questa stanza: aggiungili nel <a href="#/catalogo">Catalogo</a> (foto + misure).</span>`) +
      (da3d && prodotti.length ? `<a class="link piccolo" href="#/catalogo">+ aggiungi al catalogo</a>` : "");
    disegnaPareteLuci();
    box.querySelectorAll("[data-catalogo]").forEach((b) => b.onclick = () => {
      daCatalogo = c.prodotti.find((p) => p.id === b.dataset.catalogo);
      box.querySelectorAll("[data-catalogo]").forEach((x) => x.classList.toggle("attivo", x === b));
      document.querySelector('#r-modi [data-modo="mobili"]').click();
      dovePosare(daCatalogo.nome);
    });
  }
  $("#r-rapidi").innerHTML = rapidi.filter((n) => preset.mobili[n]).map((n) => `<button type="button" data-rapido="${n}">+ ${n}</button>`).join("");
  document.querySelectorAll("[data-rapido]").forEach((b) => b.onclick = () => {
    document.querySelectorAll("[data-rapido]").forEach((x) => x.classList.toggle("attivo", x === b));
    $("#r-tipo-mobile").value = b.dataset.rapido;
    document.querySelector('#r-modi [data-modo="mobili"]').click();
    $("#r-tipo-mobile").value = b.dataset.rapido;
    dovePosare(b.dataset.rapido);
  });

  $("#r-file-rif").addEventListener("change", () => {
    const f = $("#r-file-rif").files[0];
    if (f && destinazioneRif) caricaRif(f, destinazioneRif.destinazione, destinazioneRif.mobile);
  });
  disegnaRiferimenti();

  function disegnaVarianti() {
    if (!conVarianti) return;
    const barra = $("#r-varianti");
    barra.hidden = false;
    barra.innerHTML = Object.keys(dati.varianti).map((k) =>
      `<button type="button" data-var="${k}" class="${k === dati.variante ? "attivo" : ""}">Variante ${k}</button>`).join("") +
      `<button type="button" class="azione" data-nuova="vuota">+ Nuova variante</button>
       <button type="button" class="azione" data-nuova="copia" style="margin-left:0">Duplica questa</button>`;
    barra.querySelectorAll("[data-var]").forEach((b) => b.onclick = () => passaA(b.dataset.var));
    barra.querySelectorAll("[data-nuova]").forEach((b) => b.onclick = () => {
      const chiavi = Object.keys(dati.varianti);
      if (chiavi.length >= 5) { avviso("Massimo 5 varianti."); return; }
      const nuova = String.fromCharCode(65 + chiavi.length);
      dati.varianti[dati.variante] = dati.mobili;
      dati.varianti[nuova] = b.dataset.nuova === "copia" ? JSON.parse(JSON.stringify(dati.mobili)) : [];
      passaA(nuova);
    });
  }
  function passaA(k) {
    dati.varianti[dati.variante] = dati.mobili;
    dati.variante = k; dati.mobili = dati.varianti[k];
    disegnaVarianti(); disegnaListe(); disegnaPunti(); aggiornaGuida(vistaCorrente !== "foto");
    mostraGenera();
  }
  disegnaVarianti();

  // stanza misurata male (es. camera piena di mobili): si avvisa e non si genera, così non si spende per nulla.
  function mostraAllarme(ok) {
    stanzaAffidabile = ok;
    // l'avviso serve solo per Arreda (stanze vuote o semi vuote: lì l'arredo si progetta sulle misure)
    const serve = servizio === "arreda";
    const box = $("#r-allarme");
    box.hidden = ok || !serve;
    box.innerHTML = `<strong>⚠ Non sono riuscito a misurare bene questa stanza</strong>
      <span>Succede con le stanze piene di mobili. Così il risultato verrebbe sbagliato, quindi non genero.
      Se la stanza è arredata premi prima <b>🧹 Svuota la stanza</b>: senza mobili il programma la misura meglio.
      Oppure carica anche la piantina, che dà le misure vere.
      Puoi anche riprovare con una foto scattata più al centro della stanza.</span>`;
  }

  function mostraStanza(r) {
    if (!r || r.errore) {
      $("#r-misure").innerHTML = `<span class="sottile">${r ? r.errore : ""}</span>`;
      $("#r-avvisi").innerHTML = ""; return;
    }
    ultimaStanza = r.stanza; disegnaPunti(); disegnaSvg();
    mostraAllarme(r.affidabile !== false);
    $("#r-misure").innerHTML = `<div class="stanza-ok">✓ Stanza ricostruita${dati.scatola ? " (linee sistemate a mano)" : ""}</div>`;
    $("#r-avvisi").innerHTML = (r.stanza.avvisi || []).map((a) => `<li>${a}</li>`).join("");
  }

  async function salva(disegna = false, attendi = false) {
    clearTimeout(timer);
    if (conVarianti) dati.varianti[dati.variante] = dati.mobili;
    dati.altezza_camera = +$("#r-altezza").value || 1.5;
    dati.tara_porta = $("#r-tara").checked;
    dati.altezza_porta = (+$("#r-alt-porta").value || 210) / 100;
    dati.inclinazione = { pitch: +$("#r-pitch").value || 0, roll: +$("#r-roll").value || 0 };
    const esegui = async () => {
      const info = dati.angoli.length + dati.spigoli.length + Object.values(dati.pareti).flat().length;
      if (info < 4 && !dati.scatola && !dati.pianta) { mostraStanza({ errore: "Servono più clic: angoli a terra, spigoli o battiscopa di tutte le pareti." }); return null; }
      const r = await api(`/api/progetti/${id}/stanza?disegna=${disegna ? 1 : 0}`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(dati) });
      mostraStanza(r);
      return r;
    };
    if (disegna || attendi) return esegui();      // attendi: salva subito senza ridisegnare le guide
    timer = setTimeout(esegui, 350);
    return null;
  }

  async function aggiornaGuida(mostraGuida = true) {
    $("#r-attesa").hidden = false;
    try {
      const r = await salva(true);
      if (!r || r.errore) return false;
      salvato.guida = true;
      // la guida radar è uno strumento interno: al cliente non si mostra mai
      if (mostraGuida && modoTecnico) await cambiaVista("guida");
      return true;
    } finally { $("#r-attesa").hidden = true; }
  }

  async function cambiaVista(v) {
    if (v !== "foto" && !salvato.guida && !(await aggiornaGuida(false))) return;

    vistaCorrente = v;
    document.querySelectorAll("#r-viste [data-vista]").forEach((x) => x.classList.toggle("attivo", x.dataset.vista === v));
    caricaViewer();
  }

  document.querySelectorAll("#r-modi [data-modo]").forEach((b) => b.onclick = () => {
    document.querySelectorAll("#r-modi [data-modo]").forEach((x) => x.classList.remove("attivo"));
    b.classList.add("attivo"); modo = b.dataset.modo; provvisorio = null;
    $("#r-suggerimento").textContent = suggerimenti[modo];
    $("#r-tipo-fisso").hidden = modo !== "fissi"; $("#r-tipo-mobile").hidden = modo !== "mobili";
    $("#r-parete").hidden = modo !== "battiscopa";
    $("#r-contenitore").style.cursor = modo === "naviga" ? "" : "crosshair";
    if (modo === "linee") { if (vistaCorrente !== "guida") cambiaVista("guida"); }
    else if (modo !== "naviga" && vistaCorrente !== "foto") cambiaVista("foto");
    disegnaPunti();
  });
  document.querySelectorAll("#r-viste [data-vista]").forEach((b) => b.onclick = () => cambiaVista(b.dataset.vista));
  $("#r-aggiorna").onclick = () => aggiornaGuida(true);
  ["#r-tara", "#r-alt-porta"].forEach((s) => $(s).addEventListener("change", () => salva()));
  ["#r-altezza", "#r-pitch", "#r-roll"].forEach((s) => $(s).addEventListener("change", async () => {
    await salva(true); if (s !== "#r-altezza") caricaViewer();
  }));
  $("#r-cancella-angoli").onclick = () => {
    dati.angoli = []; dati.spigoli = []; dati.pareti = {}; dati.soffitto = null; delete dati.scatola;
    disegnaPunti(); disegnaListe(); salva(); };
  function mostraGenera() {
    const b = $("#r-conferma");
    const etichette = { rinnova: "Genera il 360 · circa 0,30 €", prodotto: "Prova nella stanza · circa 0,15 €",
      riprogetta: `Genera variante ${dati.variante || "A"} · circa 0,30 €`, arreda: `Genera variante ${dati.variante || "A"} · circa 0,30 €` };
    // progetti da piantina: render 3D con Blender sul PC, nessun costo AI
    const motore3d = dettaglio.origine === "piantina";
    b.textContent = motore3d ? `Genera il 360 in 3D · variante ${dati.variante || "A"}` : etichette[servizio];
    b.onclick = async () => {
      const domande = { rinnova: "Avvio la ristrutturazione con ChatGPT?", prodotto: "Provo il prodotto nella stanza?",
        riprogetta: `Genero la variante ${dati.variante}?`, arreda: `Genero la variante ${dati.variante}?` };
      if (!stanzaAffidabile && servizio === "arreda") {   // solo Arreda si ferma se la stanza è misurata male
        $("#r-allarme").scrollIntoView({ behavior: "smooth", block: "center" }); return;
      }
      // controlli prima di spendere: ogni servizio deve avere quello che gli serve
      if (servizio === "prodotto") {
        const conFoto = (x) => riferimenti.some((r) => r.destinazione === "mobile" && r.mobile === x.nome);
        const senzaTesto = dati.prodotti.find((x) => conFoto(x) && !(x.istruzione || "").trim());
        if (senzaTesto) {
          mostraMessaggio(`Scrivi cosa vuoi fare con ${senzaTesto.nome} (es. «sostituisci il letto con questo»).`);
          vaiA("stile"); return;
        }
        const qualcosa = dati.prodotti.some((x) => (x.istruzione || "").trim()) || riferimenti.some((r) => r.destinazione !== "mobile");
        if (!qualcosa) {
          mostraMessaggio("Carica la foto del prodotto e scrivi cosa vuoi fare (es. «sostituisci il letto con questo»).");
          vaiA("stile"); return;
        }
      }
      if (servizio === "arreda" && !dati.mobili.length) {
        mostraMessaggio("Prima decidi l'arredo: premi ✨ Proponi arredo oppure aggiungi i mobili.");
        vaiA("disposizione"); return;
      }
      if (!motore3d && servizio !== "prodotto" && !richiestaCorrente.trim() && !riferimenti.some((r) => r.destinazione !== "mobile")) {
        mostraMessaggio("Scegli uno stile o scrivi due righe su come vuoi la stanza.");
        vaiA("stile"); return;
      }
      if (!(await chiediConferma(motore3d ? `Faccio il render 360 della variante ${dati.variante}?` : domande[servizio],
        motore3d ? "Blender costruisce la stanza in 3D dalle misure e fa il render: circa 2-3 minuti, nessun costo AI."
          : servizio === "prodotto" ? "Costo circa 0,10–0,15 €." : "Costo circa 0,20–0,35 €.", "Avvia"))) return;
      b.disabled = true; b.textContent = "Avvio…";
      $("#r-attesa").lastChild.textContent = motore3d ? "Preparo la stanza per il render 3D…" : "Avvio la generazione…";
      $("#r-attesa").hidden = false;
      try {
        await salva(true);   // stanza e guida interna aggiornate (il cliente non le vede)
        await api(`/api/progetti/${id}/conferma-rilievo`, { method: "POST" });
        await api(`/api/progetti/${id}/genera`, { method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ variante: conVarianti ? dati.variante : null }) });
        location.hash = `#/lavoro/${id}`;
      } catch (e) { $("#r-attesa").hidden = true; avviso(e.message); b.disabled = false; mostraGenera(); }
    };
  }
  // un solo pulsante: Genera (niente passaggio "conferma rilievo" per il cliente)
  mostraGenera();

  disegnaListe();
  if (salvato.stanza) { ultimaStanza = salvato.stanza; mostraAllarme(salvato.affidabile !== false); }

  // ---- PIANTINA 2D (tutti i progetti): misure, porte e finestre, fotocamera, mobili trascinabili.
  // Si disegna dalla stanza calcolata (sistema della stanza, in metri). Da piantina si modifica tutto;
  // da foto 360 si può tarare con una misura vera presa col metro.
  const daPiantina = dettaglio.origine === "piantina" && !!dati.pianta;
  let modoPianta = "misure";            // "misure" (passo La stanza) oppure "arredo" (passo Disposizione)
  let timerP = null;
  const aggiornaModello = () => {
    clearTimeout(timerP);
    timerP = setTimeout(async () => {
      $("#r-attesa").hidden = false;
      try { await salva(true); if (daPiantina || vistaCorrente === "guida") caricaViewer(); } finally { $("#r-attesa").hidden = true; }
    }, 450);
  };
  const misureStimate = () => !daPiantina && !dati.misura_vera && !dati.misure_piantina;
  function provenienzaMisure() {
    if (daPiantina) return "Misure lette dalla piantina: correggile qui se qualcosa non torna.";
    if (dati.misura_vera) return `Misure tarate sulla tua misura (parete ${dati.misura_vera.parete}: ${dati.misura_vera.cm} cm).`;
    if (dati.misure_piantina) return "Misure in scala con la piantina che hai caricato.";
    return "Misure stimate dalla foto (precisione circa ±5%). Se hai misurato una parete col metro, scrivila qui: tutto si adegua.";
  }

  function disegnaPannelloPianta() {
    const box = $("#r-pianta");
    box.hidden = false;
    const P = dati.pianta;
    const arredo = modoPianta === "arredo";
    const campo = (k, etichetta) =>
      `<label>${etichetta} <input type="number" data-p="${k}" value="${P[k]}" min="50" max="3000" step="1"> cm</label>`;
    const campi = arredo ? "" : daPiantina
      ? `<div class="campi-riga">${campo("larghezza", "Larghezza")}${campo("profondita", "Profondità")}${campo("altezza", "Altezza")}</div>
         <div class="etichetta-piccola">Porte e finestre</div>
         <div id="r-aperture" class="aperture"></div>
         <div class="campi-riga">
           <button type="button" class="bottone piccolo" data-nuova-ap="porta">+ Porta</button>
           <button type="button" class="bottone piccolo" data-nuova-ap="finestra">+ Finestra</button>
           <button type="button" class="bottone piccolo" data-nuova-ap="porta-finestra">+ Porta-finestra</button>
         </div>
         <div class="campi-riga"><label>Tipo di stanza <select id="r-tipo-stanza">${Object.entries(NOMI_STANZA).map(([k, n]) =>
           `<option value="${k}" ${k === tipoStanza ? "selected" : ""}>${n}</option>`).join("")}</select></label></div>
         <p class="sottile">Decide cosa ti propone il programma: in un bagno solo sanitari, docce, vasche e mobili bagno del catalogo, e gli schemi delle piastrelle.</p>
         <p class="sottile">Il punto oro è dove "scatti" il 360: trascinalo per cambiare il punto di vista.</p>
         <div class="campi-riga"><label>Altezza fotocamera <input type="number" id="r-camera-h" value="${P.camera_h || 150}"
           min="80" max="200" step="5"> cm</label></div>
         <p class="sottile">Come il treppiede vero. Nelle stanze piccole (bagni) 120-130 cm fa sembrare la stanza più ampia
           e meno "dall'alto"; 150 cm è l'altezza degli occhi.</p>`
      : `${(() => {
           const s = ultimaStanza;
           if (!s) return "";
           const a = (s.XR - s.XL) * (s.ZW - s.ZB), lato = Math.max(s.XR - s.XL, s.ZW - s.ZB);
           return a > 40 || lato > 8 ? `<div class="avviso-misure">⚠ Le misure sembrano troppo grandi (${a.toFixed(0)} m²).
             Specchi o vetrate possono ingannare il rilievo: trascina le pareti al loro posto oppure carica la piantina.</div>` : "";
         })()}
         <p class="sottile">Le <b>linee gialle</b> nel 360 sono le pareti trovate. Se una non cade alla base del muro vero,
           <b>prendi un pallino e mettilo sul punto vero</b>: in basso dove il muro tocca il pavimento, in alto dove tocca
           il soffitto (angoli bianchi = due pareti insieme; pallini gialli = una parete; in alto a metà parete = altezza).
           Puoi correggere anche qui nella piantina, con i pallini ⇕ / ⇔.</p>
         <div class="misura-vera">
           <div class="etichetta-piccola">Hai misurato una parete col metro?</div>
           <div class="campi-riga">
             <label>Parete <select id="mv-parete">${["A", "B", "C", "D"].map((l) =>
               `<option ${dati.misura_vera && dati.misura_vera.parete === l ? "selected" : ""}>${l}</option>`).join("")}</select></label>
             <label><input type="number" id="mv-cm" min="50" step="1" placeholder="es. 312" value="${dati.misura_vera ? dati.misura_vera.cm : ""}"> cm</label>
             <button type="button" class="bottone piccolo primario" id="mv-applica">Applica</button>
           </div>
           <p class="sottile">Le lettere delle pareti sono scritte sulla piantina e sulla foto 360.</p>
         </div>`;
    box.innerHTML = `<div class="pianta-testa">
        <div><h2>${arredo ? "Piantina con l'arredo" : "Piantina della stanza"}</h2>
          <p class="sottile">${arredo ? "Trascina i mobili dove vuoi con il mouse o il dito: quelli «al muro» si appoggiano da soli alla parete."
            : provenienzaMisure()}</p></div>
        ${dettaglio.piantina ? `<a class="bottone" target="_blank" href="/api/progetti/${id}/file/${dettaglio.piantina}">Piantina originale</a>` : ""}
      </div>
      <div class="pianta-corpo ${arredo ? "solo-svg" : ""}">
        <svg id="r-svg" role="img" aria-label="Piantina della stanza"></svg>
        ${campi ? `<div class="pianta-campi">${campi}</div>` : ""}
      </div>
      ${arredo && daPiantina ? `<div id="r-pareti-arredo" class="pareti-arredo"></div>` : ""}`;
    if ($("#r-tipo-stanza")) $("#r-tipo-stanza").onchange = (e) => {
      tipoStanza = e.target.value;
      api(`/api/progetti/${id}/scheda`, { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tipo_stanza: tipoStanza }) }).catch((err) => avviso(err.message));
      disegnaCatalogoRilievo();
    };
    if ($("#r-camera-h")) $("#r-camera-h").onchange = (e) => {
      P.camera_h = Math.min(200, Math.max(80, +e.target.value || 150));
      e.target.value = P.camera_h;
      aggiornaModello();
    };
    box.querySelectorAll("[data-p]").forEach((inp) => inp.onchange = () => {
      P[inp.dataset.p] = Math.max(50, +inp.value || P[inp.dataset.p]);
      aggiornaModello();
    });
    const STANDARD = { porta: [80, 210, 0], finestra: [120, 150, 90], "porta-finestra": [120, 240, 0] };
    box.querySelectorAll("[data-nuova-ap]").forEach((b) => b.onclick = () => {
      const [l, a, dv] = STANDARD[b.dataset.nuovaAp];
      P.aperture.push({ tipo: b.dataset.nuovaAp, parete: "alto", inizio_cm: Math.max(0, Math.round((P.larghezza - l) / 2)),
        larghezza_cm: l, altezza_cm: a, davanzale_cm: dv });
      disegnaAperture(); aggiornaModello();
    });
    if ($("#mv-applica")) $("#mv-applica").onclick = async () => {
      const cm = +$("#mv-cm").value, s = ultimaStanza;
      if (!s || !(cm >= 50)) { avviso("Scrivi la misura della parete in centimetri (es. 312)."); return; }
      const parete = $("#mv-parete").value;
      const misurata = (parete === "A" || parete === "C" ? s.XR - s.XL : s.ZW - s.ZB) * 100;
      // tutte le misure ricavate dalla foto sono proporzionali all'altezza della fotocamera
      dati.altezza_camera = +(s.h * cm / misurata).toFixed(3);
      $("#r-altezza").value = dati.altezza_camera;
      dati.tara_soffitto = false; dati.tara_porta = false; $("#r-tara").checked = false;
      dati.misura_vera = { parete, cm };
      $("#r-attesa").hidden = false;
      try { await salva(true); } finally { $("#r-attesa").hidden = true; }
      disegnaPannelloPianta();
      mostraMessaggio("Misure aggiornate con la tua misura.", "ok");
    };
    if (daPiantina && !arredo) disegnaAperture();
    collegaTrascinamento();
    disegnaSvg();
  }

  function disegnaAperture() {
    const P = dati.pianta;
    const NOMI_PARETI = { alto: "in alto (A)", destra: "a destra (B)", basso: "in basso (C)", sinistra: "a sinistra (D)" };
    const sel = (k, valori, v) => `<select data-ap-k="${k}">${valori.map(([val, testo]) =>
      `<option value="${val}" ${val === v ? "selected" : ""}>${testo}</option>`).join("")}</select>`;
    const num = (k, v, titolo) => `<label>${titolo}<input type="number" data-ap-k="${k}" value="${v}" min="0" step="1"></label>`;
    $("#r-aperture").innerHTML = P.aperture.map((a, i) => `<div class="apertura" data-ap="${i}">
        ${sel("tipo", [["porta", "Porta"], ["finestra", "Finestra"], ["porta-finestra", "Porta-finestra"], ["passaggio", "Passaggio"]], a.tipo)}
        ${sel("parete", Object.entries(NOMI_PARETI), a.parete)}
        ${num("inizio_cm", a.inizio_cm, "dall'angolo")}${num("larghezza_cm", a.larghezza_cm, "larga")}
        ${num("altezza_cm", a.altezza_cm, "alta")}${num("davanzale_cm", a.davanzale_cm, "da terra")}
        <button type="button" class="link x" data-ap-togli="${i}" title="Togli">×</button></div>`).join("")
      || `<p class="sottile">Nessuna porta o finestra.</p>`;
    document.querySelectorAll("#r-aperture [data-ap-k]").forEach((el) => el.onchange = () => {
      const a = P.aperture[+el.closest("[data-ap]").dataset.ap];
      a[el.dataset.apK] = el.tagName === "SELECT" ? el.value : Math.max(0, +el.value || 0);
      aggiornaModello();
    });
    document.querySelectorAll("#r-aperture [data-ap-togli]").forEach((b) => b.onclick = () => {
      P.aperture.splice(+b.dataset.apTogli, 1); disegnaAperture(); aggiornaModello();
    });
  }

  const NS = "http://www.w3.org/2000/svg";
  disegnaSvg = function () {
    const s = ultimaStanza, svg = $("#r-svg");
    if (!s || !svg) return;
    const el = (tag, attr, testo) => {
      const e = document.createElementNS(NS, tag);
      Object.entries(attr).forEach(([k, v]) => e.setAttribute(k, v));
      if (testo != null) e.textContent = testo;
      svg.appendChild(e);
      return e;
    };
    const W = Math.round((s.XR - s.XL) * 100), D = Math.round((s.ZW - s.ZB) * 100), m = Math.max(W, D) * 0.16;
    const X = (x) => (x - s.XL) * 100, Y = (z) => (s.ZW - z) * 100;      // in alto nella piantina = parete A (fondo)
    svg.setAttribute("viewBox", `${-m} ${-m} ${W + 2 * m} ${D + 2 * m}`);
    svg.innerHTML = "";
    const fs = Math.max(W, D) * 0.035;
    el("rect", { x: 0, y: 0, width: W, height: D, class: "pv-stanza" });
    (s.mobili || []).forEach((sm, i) => {
      if (!sm.centro_m) return;
      const x = X(sm.centro_m[0]), y = Y(sm.centro_m[1]);
      const giro = Math.round((sm.rot || 0) / 90) % 2 === 1;
      const L = (giro ? sm.P : sm.L) * 100, Pp = (giro ? sm.L : sm.P) * 100;
      const classe = `pv-mobile${modoPianta === "arredo" ? " trascinabile" : ""}`;
      const r = sm.forma === "cilindro"
        ? el("circle", { cx: x, cy: y, r: sm.L * 50, class: classe, "data-mobile": i })
        : el("rect", { x: x - L / 2, y: y - Pp / 2, width: L, height: Pp, class: classe, "data-mobile": i });
      r.style.fill = `hsl(${(i * 47) % 360} 55% 62% / .55)`;
      el("text", { x, y, class: "pv-testo-mobile", "font-size": fs * 0.8 }, sm.nome || "");
    });
    (s.fissi || []).forEach((f) => {
      const [u0, u1] = f.u;
      const [x1, y1, x2, y2] = { fondo: [X(u0), Y(s.ZW), X(u1), Y(s.ZW)], dietro: [X(u0), Y(s.ZB), X(u1), Y(s.ZB)],
        sinistra: [X(s.XL), Y(u0), X(s.XL), Y(u1)], destra: [X(s.XR), Y(u0), X(s.XR), Y(u1)] }[f.parete];
      el("line", { x1, y1, x2, y2, class: `pv-apertura ${f.tipo}` });
    });
    const circa = misureStimate() ? "≈ " : "";
    el("text", { x: W / 2, y: -m * 0.45, class: "pv-quota", "font-size": fs }, `${circa}${W} cm`);
    el("text", { x: -m * 0.45, y: D / 2, class: "pv-quota", "font-size": fs, transform: `rotate(-90 ${-m * 0.45} ${D / 2})` }, `${circa}${D} cm`);
    [["A", W / 2, -m * 0.12], ["C", W / 2, D + m * 0.3], ["D", -m * 0.18, D * 0.2], ["B", W + m * 0.18, D * 0.2]]
      .forEach(([n, x, y]) => el("text", { x, y, class: "pv-parete", "font-size": fs * 0.75 }, `Parete ${n}`));
    if (!daPiantina && modoPianta === "misure") {
      // pareti trascinabili: fascia larga sopra ogni parete + maniglia oro SEMPRE visibile a metà parete
      // (con il dito non c'è il "passaggio del mouse": la maniglia dice da sola che si può trascinare)
      const sp = Math.max(W, D) * 0.05;
      [["XL", 0, 0, 0, D], ["XR", W, 0, W, D], ["ZW", 0, 0, W, 0], ["ZB", 0, D, W, D]].forEach(([k, x1, y1, x2, y2]) => {
        const verticale = k[0] === "X";
        const g = el("g", { class: `pv-muro ${verticale ? "verticale" : "orizzontale"}`, "data-muro": k });
        g.appendChild(el("line", { x1, y1, x2, y2, class: "pv-muro-fascia", "stroke-width": sp }));
        const mx = (x1 + x2) / 2, my = (y1 + y2) / 2;
        g.appendChild(el("circle", { cx: mx, cy: my, r: fs * 0.75, class: "pv-maniglia" }));
        g.appendChild(el("text", { x: mx, y: my, class: "pv-freccia", "font-size": fs * 0.95 }, verticale ? "⇔" : "⇕"));
      });
    }
    const spostabile = daPiantina && modoPianta === "misure";
    el("circle", { cx: X(0), cy: Y(0), r: fs * 0.55, class: `pv-camera${spostabile ? " trascinabile" : ""}`,
      ...(spostabile ? { "data-camera": 1 } : {}) });
    el("text", { x: X(0), y: Y(0) + fs * 1.5, class: "pv-parete", "font-size": fs * 0.65 }, "punto del 360");
  };

  // ===== ELEMENTI A PARETE E LUCI (progetti 3D) =====
  // Specchi, pensili, mensole, applique: si mettono al muro come i mobili, con l'altezza da terra.
  // Si spostano anche in altezza nella "vista delle pareti" sotto la piantina.
  // Luci a soffitto: un clic nella piantina; temperatura della luce e atmosfera (giorno o sera) per il render.
  dati.luci = dati.luci || [];
  let luceInAttesa = null;            // luce scelta, in attesa del clic nella piantina
  let tempLuce = 3000;
  const ELEMENTI_PARETE = ["Specchio", "Specchio retroilluminato", "Pensile bagno", "Mensola", "Colonna bagno", "Applique"];
  const TIPI_LUCE = { faretto: ["Faretto a incasso", 8], plafoniera: ["Plafoniera", 20], sospensione: ["Lampada a sospensione", 16] };
  const PARETE_DA_ROT = { 0: "fondo", 180: "dietro", 270: "sinistra", 90: "destra" };
  const eLuce = (p) => p.categoria === "Illuminazione";
  const aSoffitto = (p) => eLuce(p) && (p.tipo_luce || "faretto") !== "applique";

  // posizione lungo la parete (metri da sinistra, guardando la parete) <-> punto della stanza
  function lungoParete(k, x, z) {
    const s = ultimaStanza;
    return { fondo: x - s.XL, destra: s.ZW - z, dietro: s.XR - x, sinistra: z - s.ZB }[k];
  }
  function puntoDaParete(k, pos) {
    const s = ultimaStanza;
    return { fondo: [s.XL + pos, s.ZW - 0.1], destra: [s.XR - 0.1, s.ZW - pos], dietro: [s.XR - pos, s.ZB + 0.1],
      sinistra: [s.XL + 0.1, s.ZB + pos] }[k];
  }
  function aggiungiElemento(nome, extra) {
    const uguali = dati.mobili.filter((m) => (m.tipo || m.nome) === nome).length;
    dati.mobili.push({ nome: uguali ? `${nome} ${uguali + 1}` : nome, tipo: nome, ...preset.mobili[nome], rotazione: 0, ...extra });
  }

  // ✨ specchio centrato sopra il lavabo: largo come il mobile (massimo 100 cm), 20 cm sopra il piano
  async function specchioSopraLavabo(retro, p = null) {
    await salva(false, true);                 // stanza aggiornata con gli ultimi pezzi messi
    const s = ultimaStanza;
    const i = (s && s.mobili || []).findIndex((m) => /lavabo|mobile bagno|lavandino/i.test(`${m.nome} ${m.tipo}`) && m.centro_m);
    if (i < 0) { mostraMessaggio("Prima metti il mobile lavabo nella piantina."); return; }
    const sm = s.mobili[i];
    const nome = p ? p.nome : retro ? "Specchio retroilluminato" : "Specchio";
    const dove = { centro: [...sm.centro_m], parete: PARETE_DA_ROT[Math.round(sm.rot) % 360], quota: Math.round((sm.quota_m + sm.A) * 100 + 20) };
    if (p) dati.mobili.push({ nome: p.nome, tipo: `${p.categoria} ${p.nome}`, larghezza: p.larghezza, profondita: p.profondita,
      altezza: p.altezza, forma: "box", muro: true, rotazione: 0, catalogo: p.id, ...dove });
    else aggiungiElemento(nome, { larghezza: Math.min(100, Math.round(sm.L * 100)), ...dove });
    disegnaListe(); aggiornaModello();
    mostraMessaggio(`${nome} messo sopra il lavabo. Puoi spostarlo nella vista delle pareti, sotto la piantina.`, "ok");
  }
  // ✨ due applique ai lati dello specchio, a metà della sua altezza
  async function appliqueAiLati() {
    await salva(false, true);
    const s = ultimaStanza;
    const i = (s && s.mobili || []).findIndex((m) => /specchio/i.test(`${m.nome} ${m.tipo}`) && m.centro_m);
    if (i < 0) { mostraMessaggio("Prima metti lo specchio (es. ✨ Specchio sopra il lavabo)."); return; }
    const sm = s.mobili[i], k = PARETE_DA_ROT[Math.round(sm.rot) % 360];
    const pos = lungoParete(k, ...sm.centro_m);
    [-1, 1].forEach((lato) => aggiungiElemento("Applique", {
      centro: puntoDaParete(k, pos + lato * (sm.L / 2 + 0.12)), parete: k,
      quota: Math.round((sm.quota_m + sm.A / 2) * 100 - 11) }));
    disegnaListe(); aggiornaModello();
    mostraMessaggio("Due applique ai lati dello specchio.", "ok");
  }
  // faretti in automatico: uno ogni 1,2 m circa, a griglia
  function farettiAutomatici() {
    const s = ultimaStanza;
    if (!s) return;
    const W = s.XR - s.XL, D = s.ZW - s.ZB, col = Math.max(1, Math.round(W / 1.2)), righe = Math.max(1, Math.round(D / 1.2));
    dati.luci = dati.luci.filter((l) => l.tipo !== "faretto" || l.catalogo);
    for (let i = 0; i < col; i++) for (let j = 0; j < righe; j++)
      dati.luci.push({ tipo: "faretto", k: tempLuce, centro: [s.XL + (i + 0.5) * W / col, s.ZB + (j + 0.5) * D / righe] });
    salva(); disegnaSvg(); disegnaPareteLuci();
    mostraMessaggio(`${col * righe} faretti a soffitto. Trascinali nella piantina per spostarli.`, "ok");
  }

  function disegnaPareteLuci() {
    const box = $("#r-parete-luci");
    if (!box) return;
    const da3d = dettaglio.origine === "piantina" && !!dati.pianta;
    box.hidden = !conVarianti || !da3d;
    if (box.hidden) return;
    const catLuci = catalogoProdotti.filter(aSoffitto);
    const bagno = tipoStanza === "bagno";
    box.innerHTML = `<div class="gruppo-elementi"><span class="etichetta-piccola">🪞 A parete</span>
        ${bagno ? `<button type="button" class="magico-piccolo" data-auto="specchio">✨ Specchio sopra il lavabo</button>
          <button type="button" class="magico-piccolo" data-auto="specchio-led">✨ Specchio retroilluminato sopra il lavabo</button>
          ${catalogoProdotti.filter((p) => p.categoria === "Specchio").map((p) =>
            `<button type="button" class="magico-piccolo" data-specchio-cat="${p.id}">✨ ${p.nome} sopra il lavabo</button>`).join("")}
          <button type="button" class="magico-piccolo" data-auto="applique">✨ Applique ai lati dello specchio</button>` : ""}
        ${ELEMENTI_PARETE.filter((n) => preset.mobili[n] && (bagno || !/bagno/i.test(n))).map((n) =>
          `<button type="button" data-rapido="${n}">+ ${n}</button>`).join("")}
      </div>
      <div class="gruppo-elementi"><span class="etichetta-piccola">💡 Luci a soffitto</span>
        <button type="button" class="magico-piccolo" data-auto="faretti">✨ Faretti in automatico</button>
        ${Object.entries(TIPI_LUCE).map(([k, [n]]) => `<button type="button" data-luce="${k}">+ ${n}</button>`).join("")}
        ${catLuci.map((p) => `<button type="button" data-luce-cat="${p.id}">${p.stato_modello === "pronto" ? "🧊 " : ""}${p.nome}</button>`).join("")}
        <label class="sottile">Luce <select id="r-temp-luce">
          ${[[2700, "molto calda 2700 K"], [3000, "calda 3000 K"], [4000, "naturale 4000 K"]].map(([k, n]) =>
            `<option value="${k}" ${tempLuce === k ? "selected" : ""}>${n}</option>`).join("")}</select></label>
      </div>
      ${dati.luci.length ? `<div class="luci-elenco">${dati.luci.map((l, i) => `<span class="chip">💡 ${l.nome || (TIPI_LUCE[l.tipo] || ["Luce"])[0]}
        <button type="button" class="link x" data-togli-luce="${i}" title="Togli">✕</button></span>`).join("")}
        <button type="button" class="link piccolo" data-togli-luce="tutte">togli tutte</button></div>` : ""}
      <div class="gruppo-elementi"><span class="etichetta-piccola">Atmosfera del render</span>
        <div class="interruttore">${[["giorno", "☀ Giorno"], ["sera", "🌙 Sera (solo luci accese)"]].map(([k, n]) =>
          `<button type="button" data-atmosfera="${k}" class="${(dati.atmosfera || "giorno") === k ? "attivo" : ""}">${n}</button>`).join("")}</div>
      </div>`;
    box.querySelectorAll("[data-rapido]").forEach((b) => b.onclick = () => {
      document.querySelector('#r-modi [data-modo="mobili"]').click();
      $("#r-tipo-mobile").value = b.dataset.rapido;
      dovePosare(b.dataset.rapido);
    });
    box.querySelectorAll("[data-auto]").forEach((b) => b.onclick = () => ({
      specchio: () => specchioSopraLavabo(false), "specchio-led": () => specchioSopraLavabo(true),
      applique: appliqueAiLati, faretti: farettiAutomatici }[b.dataset.auto])());
    box.querySelectorAll("[data-specchio-cat]").forEach((b) => b.onclick = () =>
      specchioSopraLavabo(false, catalogoProdotti.find((p) => p.id === b.dataset.specchioCat)));
    box.querySelectorAll("[data-luce]").forEach((b) => b.onclick = () => {
      luceInAttesa = { tipo: b.dataset.luce, nome: TIPI_LUCE[b.dataset.luce][0] };
      modo = "naviga";
      mostraMessaggio(`Clicca nella piantina dove va: ${luceInAttesa.nome}.`, "ok");
      $("#r-pianta").scrollIntoView({ behavior: "smooth", block: "center" });
    });
    box.querySelectorAll("[data-luce-cat]").forEach((b) => b.onclick = () => {
      const p = catalogoProdotti.find((x) => x.id === b.dataset.luceCat);
      luceInAttesa = { tipo: p.tipo_luce || "faretto", nome: p.nome, catalogo: p.id, k: +p.k || tempLuce };
      modo = "naviga";
      mostraMessaggio(`Clicca nella piantina dove va: ${p.nome}.`, "ok");
      $("#r-pianta").scrollIntoView({ behavior: "smooth", block: "center" });
    });
    $("#r-temp-luce").onchange = (e) => {
      tempLuce = +e.target.value;
      dati.luci.forEach((l) => { if (!l.catalogo) l.k = tempLuce; });   // le luci del catalogo tengono la loro
      salva();
    };
    box.querySelectorAll("[data-togli-luce]").forEach((b) => b.onclick = () => {
      if (b.dataset.togliLuce === "tutte") dati.luci = []; else dati.luci.splice(+b.dataset.togliLuce, 1);
      salva(); disegnaSvg(); disegnaPareteLuci();
    });
    box.querySelectorAll("[data-atmosfera]").forEach((b) => b.onclick = () => {
      dati.atmosfera = b.dataset.atmosfera; salva(); disegnaPareteLuci();
    });
  }

  // ---- vista delle pareti nel passo Arredo: i pezzi "al muro" visti di fronte, trascinabili (in altezza solo se sospesi)
  function disegnaParetiArredo() {
    const box = $("#r-pareti-arredo"), s = ultimaStanza;
    if (!box || !s) return;
    const H = s.H * 100, gap = 30;
    let ox = 0, corpo = "";
    const posizioni = [];
    [["fondo", "A"], ["destra", "B"], ["dietro", "C"], ["sinistra", "D"]].forEach(([k, lettera]) => {
      const L = (k === "fondo" || k === "dietro" ? s.XR - s.XL : s.ZW - s.ZB) * 100;
      let g = `<rect x="0" y="0" width="${L}" height="${H}" fill="#fbfaf8" stroke="#2b2b2b" stroke-width="1.5"/>`;
      (s.fissi || []).filter((f) => f.parete === k).forEach((f) => {
        const p = f.u.map((u) => lungoParete(k, ...(k === "fondo" || k === "dietro" ? [u, 0] : [0, u])) * 100);
        g += `<rect x="${Math.min(...p)}" y="${H - f.v[1] * 100}" width="${Math.abs(p[1] - p[0])}" height="${(f.v[1] - f.v[0]) * 100}"
          fill="${f.tipo === "finestra" ? "#dcebf7" : "#fff"}" stroke="#8a8378"/>`;
      });
      (s.mobili || []).forEach((sm, i) => {
        if (!sm.centro_m || !(dati.mobili[i] || {}).muro || PARETE_DA_ROT[Math.round(sm.rot) % 360] !== k) return;
        const c = lungoParete(k, ...sm.centro_m) * 100, w = sm.L * 100, y0 = sm.quota_m * 100, a = sm.A * 100;
        const sospeso = sm.quota_m > 0.05 || ELEMENTI_PARETE.some((n) => (sm.tipo || "").startsWith(n));
        posizioni.push({ i, k, ox, L, sospeso });
        g += `<g class="el-parete${sospeso ? " sospeso" : ""}" data-el="${posizioni.length - 1}">
          <rect x="${c - w / 2}" y="${H - y0 - a}" width="${w}" height="${Math.max(a, 3)}" fill="hsl(${(i * 47) % 360} 55% 62% / .6)" stroke="#5b5348"/>
          <text x="${c}" y="${H - y0 - a / 2}" text-anchor="middle" dominant-baseline="middle" font-size="11">${sm.nome}</text>
          ${sospeso ? `<text x="${c}" y="${H - y0 + 13}" text-anchor="middle" font-size="10" fill="#6f6a62">${Math.round(y0)} cm da terra</text>` : ""}</g>`;
      });
      g += `<text x="${L / 2}" y="${H + 22}" text-anchor="middle" font-size="16" font-weight="600">Parete ${lettera}</text>`;
      corpo += `<g transform="translate(${ox} 0)">${g}</g>`;
      ox += L + gap;
    });
    box.innerHTML = `<div class="etichetta-piccola">Le pareti viste di fronte</div>
      <svg viewBox="-6 -10 ${ox - gap + 12} ${H + 40}" class="pareti-aperte" role="img" aria-label="Le pareti con i pezzi al muro">${corpo}</svg>
      <p class="sottile">Trascina specchi, pensili, mensole e applique anche in su e in giù; i mobili a terra si spostano lungo la parete.</p>`;
    const svg = box.querySelector("svg");
    box.querySelectorAll("[data-el]").forEach((el) => el.addEventListener("pointerdown", (e) => {
      e.preventDefault();
      const info = posizioni[+el.dataset.el], sm = s.mobili[info.i], m = dati.mobili[info.i];
      const pt = (ev) => { const p = svg.createSVGPoint(); p.x = ev.clientX; p.y = ev.clientY; return p.matrixTransform(svg.getScreenCTM().inverse()); };
      const inizio = pt(e);
      let dx = 0, dy = 0;
      const muovi = (ev) => {
        const q = pt(ev);
        dx = q.x - inizio.x; dy = info.sospeso ? q.y - inizio.y : 0;
        el.setAttribute("transform", `translate(${dx} ${dy})`);
      };
      const fine = () => {
        window.removeEventListener("pointermove", muovi); window.removeEventListener("pointerup", fine);
        if (Math.hypot(dx, dy) < 2) { el.removeAttribute("transform"); return; }
        const pos = Math.min(info.L - sm.L * 50, Math.max(sm.L * 50, lungoParete(info.k, ...sm.centro_m) * 100 + dx)) / 100;
        m.centro = puntoDaParete(info.k, pos);
        m.parete = info.k;
        delete m.clic;
        if (info.sospeso) m.quota = Math.max(0, Math.round(sm.quota_m * 100 - dy));
        disegnaListe(); aggiornaModello();
      };
      window.addEventListener("pointermove", muovi); window.addEventListener("pointerup", fine);
    }));
  }

  // la piantina disegna anche le luci (cerchi gialli) e le riceve con un clic
  const disegnaSvgBase = disegnaSvg;
  disegnaSvg = function () {
    disegnaSvgBase();
    const s = ultimaStanza, svg = $("#r-svg");
    if (!s || !svg) return;
    const X = (x) => (x - s.XL) * 100, Y = (z) => (s.ZW - z) * 100;
    dati.luci.forEach((l, i) => {
      const c = document.createElementNS(NS, "circle");
      Object.entries({ cx: X(l.centro[0]), cy: Y(l.centro[1]), r: (TIPI_LUCE[l.tipo] || [0, 8])[1], class: "pv-luce", "data-luce": i })
        .forEach(([k, v]) => c.setAttribute(k, v));
      svg.appendChild(c);
    });
    if (modoPianta === "arredo" && daPiantina) disegnaParetiArredo();
    if (svg.dataset.luciCollegate) return;
    svg.dataset.luciCollegate = "1";
    const punto = (e) => { const p = svg.createSVGPoint(); p.x = e.clientX; p.y = e.clientY; return p.matrixTransform(svg.getScreenCTM().inverse()); };
    svg.addEventListener("pointerdown", (e) => {
      const st = ultimaStanza;
      if (modoPianta !== "arredo" || !st) return;
      if (luceInAttesa) {
        const q = punto(e);
        dati.luci.push({ ...luceInAttesa, k: luceInAttesa.k || tempLuce, centro: [q.x / 100 + st.XL, st.ZW - q.y / 100] });
        luceInAttesa = null;
        salva(); disegnaSvg(); disegnaPareteLuci();
        e.stopImmediatePropagation(); e.preventDefault();
        return;
      }
      const t = e.target;
      if (t.dataset.luce == null) return;
      e.stopImmediatePropagation(); e.preventDefault();
      const i = +t.dataset.luce, a = punto(e);
      const muovi = (ev) => { const q = punto(ev); t.setAttribute("transform", `translate(${q.x - a.x} ${q.y - a.y})`); };
      const fine = (ev) => {
        window.removeEventListener("pointermove", muovi); window.removeEventListener("pointerup", fine);
        const q = punto(ev);
        dati.luci[i].centro = [dati.luci[i].centro[0] + (q.x - a.x) / 100, dati.luci[i].centro[1] - (q.y - a.y) / 100];
        salva(); disegnaSvg();
      };
      window.addEventListener("pointermove", muovi); window.addEventListener("pointerup", fine);
    }, true);
  };

  // trascinamento (mouse e dito): fotocamera (solo da piantina, passo La stanza) e mobili (passo Disposizione)
  function collegaTrascinamento() {
    const svg = $("#r-svg");
    let presa = null;
    const puntoSvg = (e) => {
      const p = svg.createSVGPoint();
      p.x = e.clientX; p.y = e.clientY;
      const q = p.matrixTransform(svg.getScreenCTM().inverse());
      return [q.x, q.y];
    };
    svg.addEventListener("pointerdown", (e) => {
      const t = e.target;
      if (t.dataset.camera) presa = { tipo: "camera", el: t };
      else if (t.closest && t.closest("[data-muro]")) {
        const g = t.closest("[data-muro]");
        presa = { tipo: "muro", k: g.dataset.muro, el: g };
      }
      else if (t.dataset.mobile != null && modoPianta === "arredo") presa = { tipo: "mobile", i: +t.dataset.mobile, el: t };
      else if (modoPianta === "arredo" && modo === "mobili" && ultimaStanza) {
        // mobile o prodotto scelto con i pulsanti: va dove si clicca nella piantina
        const [px, py] = puntoSvg(e), s = ultimaStanza;
        clic(null, [px / 100 + s.XL, s.ZW - py / 100]);
        e.preventDefault();
        return;
      }
      else return;
      presa.inizio = puntoSvg(e);
      try { svg.setPointerCapture(e.pointerId); } catch (err) { /* puntatore già rilasciato */ }
      e.preventDefault();
    });
    svg.addEventListener("pointermove", (e) => {
      if (!presa) return;
      const [x, y] = puntoSvg(e);
      presa.delta = [x - presa.inizio[0], y - presa.inizio[1]];
      if (presa.tipo === "muro") presa.delta = presa.k[0] === "X" ? [presa.delta[0], 0] : [0, presa.delta[1]];   // si muove solo avanti/indietro
      presa.el.setAttribute("transform", `translate(${presa.delta[0]} ${presa.delta[1]})`);
    });
    svg.addEventListener("pointerup", () => {
      if (!presa) return;
      const { tipo, i, delta } = presa;
      const presa_k = presa.k;
      presa = null;
      const s = ultimaStanza;
      if (!delta || Math.hypot(delta[0], delta[1]) < 2 || !s) { disegnaSvg(); return; }
      const [dx, dz] = [delta[0] / 100, -delta[1] / 100];               // da centimetri della piantina a metri
      if (tipo === "muro") {
        // la stanza diventa una "scatola" corretta a mano: pareti nel sistema della stanza, in metri
        const nuova = { h: s.h, theta: s.theta, XL: s.XL, XR: s.XR, ZB: s.ZB, ZW: s.ZW, H: s.H };
        nuova[presa_k] += presa_k[0] === "X" ? dx : dz;
        if (!(nuova.XL < -0.2 && nuova.XR > 0.2 && nuova.ZB < -0.2 && nuova.ZW > 0.2)) {
          mostraMessaggio("Così il punto del 360 resterebbe fuori dalla stanza."); disegnaSvg(); return;
        }
        dati.scatola = nuova;
        dati.altezza_camera = s.h; $("#r-altezza").value = s.h;      // stessa scala di adesso
        delete dati.misura_vera;
        aggiornaModello();
        return;
      }
      if (tipo === "camera") {
        const P = dati.pianta;
        P.camera = [Math.round(-s.XL * 100 + delta[0]), Math.round(-s.ZB * 100 - delta[1])];
        // i mobili restano fermi nella stanza: le loro coordinate sono rispetto alla fotocamera
        dati.mobili.forEach((mm, k) => {
          const sm = s.mobili[k];
          if (!sm || !sm.centro_m) return;
          mm.centro = [sm.centro_m[0] - dx, sm.centro_m[1] - dz];
          delete mm.clic;
        });
      } else {
        const sm = s.mobili[i];
        dati.mobili[i].centro = [sm.centro_m[0] + dx, sm.centro_m[1] + dz];
        delete dati.mobili[i].clic;
      }
      disegnaListe(); aggiornaModello();
    });
  }

  // ---- PERCORSO GUIDATO: un passo alla volta, con la barra dei passi e Indietro / Avanti
  const servizioScelto = daPiantina || dettaglio.servizio_scelto !== false;
  let richiestaCorrente = dettaglio.richiesta || "";
  const NOMI_PASSI = {
    stanza: "La stanza", cosa: "Cosa vuoi fare", disposizione: "Disposizione",
    stile: servizio === "prodotto" ? "Prodotti e materiali" : "Stile e materiali", genera: "Riepilogo e genera",
  };
  if (daPiantina) { NOMI_PASSI.disposizione = "Arredo"; NOMI_PASSI.stile = "Piastrelle e finiture"; }
  function passiAttivi() {
    const p = ["stanza"];
    if (!daPiantina) p.push("cosa");
    if (!servizioScelto) return p;
    if (conVarianti) p.push("disposizione");
    p.push("stile", "genera");
    return p;
  }
  const TITOLI = {
    stanza: ["Controlla la stanza", "Il programma ha misurato la stanza: guarda la piantina e correggi se qualcosa non torna."],
    cosa: ["Cosa vuoi fare in questa stanza?", "Scegli una strada: puoi sempre tornare indietro e cambiarla."],
    disposizione: ["Dove vanno le cose", "Fai proporre l'arredo a Claude oppure mettilo tu: tutto è a misura reale della stanza."],
    stile: servizio === "prodotto"
      ? ["Prodotti e materiali", "Carica la foto del prodotto e scrivi cosa farne, oppure scegli un materiale da provare."]
      : ["Stile e materiali", "Scegli lo stile e, se vuoi, carica le foto dei materiali e dei prodotti veri."],
    genera: ["Riepilogo", "Controlla le scelte e genera il 360. Puoi fare correzioni anche dopo."],
  };
  if (daPiantina) {
    TITOLI.disposizione = ["Dove vanno i pezzi", "Scegli i pezzi del tuo catalogo e clicca nella piantina dove vanno: tutto è a misura reale."];
    TITOLI.stile = ["Piastrelle e finiture", "Scegli pavimento e piastrelle del catalogo e come posarle sulle pareti."];
  }
  const CHIAVE_PASSO = `pv_passo_${id}`;
  let passo = "stanza";
  try { passo = localStorage.getItem(CHIAVE_PASSO) || "stanza"; } catch (e) { /* memoria non disponibile */ }
  if (!passiAttivi().includes(passo)) passo = "stanza";

  // la scelta "Cosa vuoi fare" (sostituisce i vecchi servizi)
  function disegnaCosa() {
    const scelte = [
      ["rinnova", "🔨", "Rifare tutto, mobili al loro posto", "Pavimenti, rivestimenti, pareti, porte e arredi nuovi, con la stessa disposizione.", "Ristruttura"],
      ["arreda", "📐", "Cambiare la disposizione", "Decidi dove vanno cucina, sanitari, letti e mobili, a misura reale. Anche più varianti.", "Progetta"],
      ["prodotto", "🧩", "Provare solo un prodotto o un materiale", "Una piastrella, un mobile, un sanitario: cambia solo quello, il resto resta identico.", "Prova prodotto"],
    ];
    const attuale = servizioScelto ? (servizio === "riprogetta" ? "arreda" : servizio) : "";
    $("#r-cosa").innerHTML = `<div class="scelte-grandi">${scelte.map(([v, ic, t, d, n]) =>
        `<button type="button" class="scelta-grande ${v === attuale ? "attivo" : ""}" data-scegli="${v}">
          <span class="icona-scelta">${ic}</span><strong>${t}</strong><span>${d}</span><em>${n}</em></button>`).join("")}</div>
      <div class="domanda-vuota" id="r-domanda-vuota" hidden>
        <strong>La stanza adesso ha dei mobili?</strong>
        <p class="sottile">Senza mobili il programma misura meglio la stanza e progetta la nuova disposizione da zero.</p>
        <div class="campi-riga">
          <button type="button" class="bottone primario" data-vuota="svuota">Sì, svuotala prima · circa 0,15 €</button>
          <button type="button" class="bottone" data-vuota="no">No, è già vuota</button>
        </div>
      </div>`;
    const salvaScelta = async (valore) => {
      await api(`/api/progetti/${id}/scheda`, { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ servizio: valore }) });
    };
    const vaiDopo = (k) => { try { localStorage.setItem(CHIAVE_PASSO, k); } catch (e) { /* niente */ } naviga(); };
    document.querySelectorAll("[data-scegli]").forEach((b) => b.onclick = async () => {
      const v = b.dataset.scegli;
      document.querySelectorAll("[data-scegli]").forEach((x) => x.classList.toggle("attivo", x === b));
      try { await salvaScelta(v); } catch (e) { avviso(e.message); return; }
      if (v === "arreda" && !dettaglio.svuotata) {
        $("#r-domanda-vuota").hidden = false;
        $("#r-domanda-vuota").scrollIntoView({ behavior: "smooth", block: "center" });
        return;
      }
      vaiDopo(v === "arreda" ? "disposizione" : "stile");
    });
    document.querySelectorAll("[data-vuota]").forEach((b) => b.onclick = async () => {
      if (b.dataset.vuota === "svuota") {
        if (!(await chiediConferma("Svuoto la stanza con ChatGPT?",
          "Toglie mobili e oggetti e tiene pareti, pavimento, porte e finestre. La foto originale resta salvata. Costo circa 0,10–0,25 €.",
          "Svuota"))) return;
        try { localStorage.setItem(CHIAVE_PASSO, "disposizione"); } catch (e) { /* niente */ }
        try { await api(`/api/progetti/${id}/svuota`, { method: "POST" }); naviga(); } catch (e) { avviso(e.message); }
      } else vaiDopo("disposizione");
    });
  }

  // stile e note (passo Stile e materiali)
  function disegnaStile() {
    if (daPiantina) {
      $("#r-stile").innerHTML = "";
      disegnaSuperfici();
      return;
    }
    const lista = servizio === "prodotto" ? [] : conVarianti ? PRESET_ARREDO : PRESET.filter((p) => p.nome !== "Svuota stanza");
    $("#r-stile").innerHTML = `${lista.length ? `<div class="etichetta-piccola">Stili pronti</div>
        <div class="chips chips-clic" id="r-stili">${lista.map((p, i) =>
          `<button type="button" class="chip ${p.testo === richiestaCorrente ? "attivo" : ""}" data-stile="${i}">${p.nome}</button>`).join("")}</div>` : ""}
      <label class="nota-libera"><span>${servizio === "prodotto" ? "Indicazioni generali (facoltative)" : "Descrivi come la vuoi"}</span>
        <textarea id="r-richiesta" rows="3" placeholder="${servizio === "prodotto" ? "Es. mantieni la luce calda della stanza."
          : "Es. moderna e luminosa, parquet rovere, pareti tortora, bagno con gres effetto pietra…"}">${richiestaCorrente.replace(/</g, "&lt;")}</textarea>
      </label>`;
    let t = null;
    const salvaRichiesta = () => {
      clearTimeout(t);
      t = setTimeout(() => api(`/api/progetti/${id}/scheda`, { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ richiesta: richiestaCorrente }) }).catch((e) => avviso(e.message)), 400);
    };
    $("#r-richiesta").oninput = () => { richiestaCorrente = $("#r-richiesta").value; salvaRichiesta(); };
    document.querySelectorAll("[data-stile]").forEach((b) => b.onclick = () => {
      document.querySelectorAll("[data-stile]").forEach((x) => x.classList.toggle("attivo", x === b));
      richiestaCorrente = lista[+b.dataset.stile].testo;
      $("#r-richiesta").value = richiestaCorrente;
      salvaRichiesta();
    });
    if (daPiantina) disegnaSuperfici();
  }

  // PIASTRELLE E SUPERFICI (progetti 3D): per ogni zona una piastrella del catalogo o una pittura, con i m² da ordinare
  // ===== PIASTRELLE E SUPERFICI (progetti 3D) =====
  // Semplice per l'impresa: 1) pavimento  2) piastrella delle pareti  3) uno SCHEMA pronto (5 scelte).
  // Il programma calcola le zone (anche dietro doccia, vasca e lavabo), le disegna sulle pareti "aperte" in scala
  // e conta i m² da ordinare. Nei "dettagli" si può comunque cambiare ogni zona a mano.
  const SCHEMI = [
    ["solo_pavimento", "Solo pavimento", "Pareti dipinte"],
    ["classico", "Classico a metà", "Rivestimento a 120 cm, doccia più alta"],
    ["tutta_altezza", "Tutta altezza", "Piastrelle fino al soffitto"],
    ["moderno", "Moderno", "Piastrelle solo dietro doccia, vasca e lavabo"],
    ["accento", "Parete d'accento", "Una parete con una piastrella diversa"],
  ];
  // disegnino di ogni schema: una parete vista di fronte (grigio = piastrella, chiaro = pittura)
  const ICONE_SCHEMI = {
    solo_pavimento: '<rect x="2" y="2" width="56" height="34" fill="#efebe4"/><rect x="2" y="36" width="56" height="6" fill="#c9a77f"/>',
    classico: '<rect x="2" y="2" width="56" height="34" fill="#efebe4"/><rect x="2" y="20" width="56" height="16" fill="#b9b4ac"/><rect x="40" y="8" width="18" height="28" fill="#b9b4ac"/><rect x="2" y="36" width="56" height="6" fill="#c9a77f"/>',
    tutta_altezza: '<rect x="2" y="2" width="56" height="34" fill="#b9b4ac"/><rect x="2" y="36" width="56" height="6" fill="#c9a77f"/>',
    moderno: '<rect x="2" y="2" width="56" height="34" fill="#efebe4"/><rect x="6" y="2" width="16" height="34" fill="#b9b4ac"/><rect x="36" y="2" width="20" height="34" fill="#b9b4ac"/><rect x="2" y="36" width="56" height="6" fill="#c9a77f"/>',
    accento: '<rect x="2" y="2" width="28" height="34" fill="#efebe4"/><rect x="30" y="2" width="28" height="34" fill="#7f8a86"/><rect x="2" y="36" width="56" height="6" fill="#c9a77f"/>',
  };
  const PARETI_ORDINE = [["fondo", "A"], ["destra", "B"], ["dietro", "C"], ["sinistra", "D"]];
  const PAROLE_ZONA = { doccia: /doccia/i, zona_vasca: /vasca/i, zona_lavabo: /lavabo|mobile bagno|lavandino|lavello/i };

  function scelte() { return (superfici.scelte = superfici.scelte || {}); }
  const piastrella = (pid) => (piastrelleCatalogo || []).find((x) => x.id === pid);
  // misura della piastrella sulla parete (cm), con il verso scelto
  function formatoMuro(p, verso) {
    if (!p) return null;
    let [w, h] = [p.larghezza, p.profondita];
    if (verso === "verticale" && p.foto_tipo !== "superficie") [w, h] = [Math.min(w, h), Math.max(w, h)];
    else if (p.foto_tipo !== "superficie") [w, h] = [Math.max(w, h), Math.min(w, h)];
    return { w, h, fuga: p.foto_tipo === "superficie" ? 0 : (p.fuga_mm || 0) / 10 };
  }
  // l'altezza del rivestimento si aggancia all'ultima fila intera (niente piastrelle tagliate in alto)
  function agganciaFila(cm) {
    const f = formatoMuro(piastrella(scelte().muro), scelte().verso);
    const H = ultimaStanza ? Math.round(ultimaStanza.H * 100) : 270;
    if (!f || f.h <= 0) return Math.min(H, cm);
    const fila = f.h + f.fuga;
    return Math.min(H, Math.max(fila, Math.round(cm / fila) * fila));
  }

  // dallo schema scelto alle zone che usa Blender
  function applicaSchema() {
    const c = scelte(), H = ultimaStanza ? Math.round(ultimaStanza.H * 100) : 270;
    const muro = c.muro ? { piastrella: c.muro, verso: c.verso } : null;
    const nuove = { scelte: c, pareti: { colore: c.colore || "#ebe6dd" } };
    if (c.pav) nuove.pavimento = { piastrella: c.pav };
    if (superfici.soffitto) nuove.soffitto = superfici.soffitto;
    const tutta = { altezza: H };
    if (muro) {
      if (c.schema === "classico") {
        nuove.rivestimento = { ...muro, altezza: c.h_riv || agganciaFila(120) };
        nuove.doccia = { ...muro, altezza: agganciaFila(210) };
      } else if (c.schema === "tutta_altezza") {
        nuove.rivestimento = { ...muro, ...tutta };
      } else if (c.schema === "moderno") {
        ["zona_lavabo", "zona_vasca", "doccia"].forEach((z) => { nuove[z] = { ...muro, ...tutta }; });
      } else if (c.schema === "accento") {
        ["doccia"].forEach((z) => { nuove[z] = { ...muro, ...tutta }; });
      }
    }
    if (c.schema === "accento" && c.accento) {
      nuove[`parete_${c.parete_accento || "fondo"}`] = { piastrella: c.accento, verso: c.verso, ...tutta };
    }
    superfici = nuove;
  }

  // ---- pareti "aperte": le 4 pareti viste da dentro la stanza, una accanto all'altra (cm)
  function pareteAperta(k) {
    const s = ultimaStanza;
    const W = s.XR - s.XL, D = s.ZW - s.ZB;
    // posizione da sinistra guardando la parete, dato un punto (x, z) della stanza
    const pos = { fondo: (x) => x - s.XL, destra: (x, z) => s.ZW - z, dietro: (x) => s.XR - x, sinistra: (x, z) => z - s.ZB }[k];
    return { lungo: k === "fondo" || k === "dietro" ? W : D, pos };
  }
  function tratti(k, zona) {
    // dove la parete k è "dietro" a doccia / vasca / lavabo (in cm da sinistra)
    const s = ultimaStanza, { pos } = pareteAperta(k);
    const piano = { fondo: ["z", s.ZW], dietro: ["z", s.ZB], destra: ["x", s.XR], sinistra: ["x", s.XL] }[k];
    const margine = zona === "zona_lavabo" ? 0.10 : 0.02;
    return (s.mobili || []).filter((m) => m.centro_m && PAROLE_ZONA[zona].test(`${m.nome} ${m.tipo}`)).map((m) => {
      const r = (m.rot || 0) * Math.PI / 180, ca = Math.cos(r), sa = Math.sin(r);
      const angoli = [];
      [-m.L / 2, m.L / 2].forEach((lx) => [-m.P / 2, m.P / 2].forEach((ly) =>
        angoli.push([m.centro_m[0] + lx * ca + ly * sa, m.centro_m[1] - lx * sa + ly * ca])));
      const vicino = Math.min(...angoli.map(([x, z]) => Math.abs((piano[0] === "x" ? x : z) - piano[1])));
      if (vicino > 0.12) return null;
      const p = angoli.map(([x, z]) => pos(x, z));
      return [(Math.min(...p) - margine) * 100, (Math.max(...p) + margine) * 100];
    }).filter(Boolean);
  }
  // strati della parete k dal basso (meno importante) all'alto (vince), come in Blender
  function stratiParete(k) {
    const H = ultimaStanza.H * 100, L = pareteAperta(k).lungo * 100;
    const alt = (z, base) => Math.min(H, (z && z.altezza) || base);
    const out = [{ spec: superfici.pareti || { colore: "#ebe6dd" }, x0: 0, x1: L, y1: H }];
    const sing = superfici[`parete_${k}`];
    if (sing) out.push({ spec: sing, x0: 0, x1: L, y1: alt(sing, H) });
    if (superfici.rivestimento) out.push({ spec: superfici.rivestimento, x0: 0, x1: L, y1: alt(superfici.rivestimento, 120), riv: true });
    [["zona_lavabo", 120], ["zona_vasca", 220], ["doccia", 220]].forEach(([z, b]) => {
      if (superfici[z]) tratti(k, z).forEach(([x0, x1]) => out.push({ spec: superfici[z], x0: Math.max(0, x0), x1: Math.min(L, x1), y1: alt(superfici[z], b) }));
    });
    return out;
  }
  function aperture(k) {
    const s = ultimaStanza, { pos } = pareteAperta(k);
    return (s.fissi || []).filter((f) => f.parete === k).map((f) => {
      const p = f.u.map((u) => (k === "fondo" || k === "dietro" ? pos(u, 0) : pos(0, u)) * 100);
      return { x0: Math.min(...p), x1: Math.max(...p), y0: f.v[0] * 100, y1: f.v[1] * 100, tipo: f.tipo };
    });
  }
  // m² per piastrella: si conta la parete a quadretti di 5 cm (stesse regole del disegno), porte e finestre escluse
  function contaMetri() {
    const conti = {};
    const aggiungi = (pid, m2) => { if (pid) conti[pid] = (conti[pid] || 0) + m2; };
    const s = ultimaStanza;
    if (!s) return conti;
    aggiungi(superfici.pavimento && superfici.pavimento.piastrella, (s.XR - s.XL) * (s.ZW - s.ZB));
    aggiungi(superfici.soffitto && superfici.soffitto.piastrella, (s.XR - s.XL) * (s.ZW - s.ZB));
    const passo = 5;
    PARETI_ORDINE.forEach(([k]) => {
      const strati = stratiParete(k), buchi = aperture(k), L = pareteAperta(k).lungo * 100, H = s.H * 100;
      for (let x = passo / 2; x < L; x += passo) for (let y = passo / 2; y < H; y += passo) {
        if (buchi.some((b) => x > b.x0 && x < b.x1 && y > b.y0 && y < b.y1)) continue;
        let top = null;
        strati.forEach((st) => { if (x > st.x0 && x < st.x1 && y < st.y1) top = st; });
        if (top && top.spec.piastrella) aggiungi(top.spec.piastrella, (passo * passo) / 10000);
      }
    });
    return conti;
  }
  function disegnaPareti(svgBox) {
    const s = ultimaStanza;
    if (!s) { svgBox.innerHTML = ""; return; }
    const H = s.H * 100, gap = 30, alto = H + 40;
    let ox = 0, defs = "", corpo = "";
    PARETI_ORDINE.forEach(([k, lettera]) => {
      const L = pareteAperta(k).lungo * 100;
      let g = "";
      stratiParete(k).forEach((st, i) => {
        const p = piastrella(st.spec.piastrella);
        let riemp = st.spec.colore || "#ebe6dd";
        if (p) {
          const f = p.foto_tipo === "superficie" ? { w: p.larghezza, h: p.profondita, fuga: 0 } : formatoMuro(p, st.spec.verso);
          const idp = `pt-${k}-${i}`;
          // le piastrelle partono intere da terra e sono centrate sulla parete (tagli uguali ai lati)
          defs += `<pattern id="${idp}" patternUnits="userSpaceOnUse" width="${f.w + f.fuga}" height="${f.h + f.fuga}"
              x="${(L / 2) % (f.w + f.fuga)}" y="${H % (f.h + f.fuga)}">
            <rect width="${f.w + f.fuga}" height="${f.h + f.fuga}" fill="${p.fuga_colore || "#b9b2a6"}"/>
            <image href="/api/catalogo/${p.id}/file/${p.foto}" width="${f.w}" height="${f.h}" preserveAspectRatio="none"/>
            ${f.fuga ? "" : `<rect width="${f.w}" height="${f.h}" fill="none" stroke="rgba(0,0,0,.08)" stroke-width="0.4"/>`}
          </pattern>`;
          riemp = `url(#${idp})`;
        }
        g += `<rect x="${st.x0}" y="${H - st.y1}" width="${st.x1 - st.x0}" height="${st.y1}" fill="${riemp}"/>`;
      });
      aperture(k).forEach((b) => {
        g += `<rect x="${b.x0}" y="${H - b.y1}" width="${b.x1 - b.x0}" height="${b.y1 - b.y0}" fill="${b.tipo === "finestra" ? "#dcebf7" : "#ffffff"}" stroke="#8a8378" stroke-width="1"/>`;
      });
      g += `<rect x="0" y="0" width="${L}" height="${H}" fill="none" stroke="#2b2b2b" stroke-width="1.5"/>
        <text x="${L / 2}" y="${H + 22}" text-anchor="middle" font-size="16" font-weight="600">Parete ${lettera}</text>
        <text x="${L / 2}" y="${H + 38}" text-anchor="middle" font-size="12" fill="#6f6a62">${Math.round(L)} cm</text>`;
      corpo += `<g transform="translate(${ox} 0)">${g}</g>`;
      ox += L + gap;
    });
    const riv = superfici.rivestimento;
    let maniglia = "";
    if (riv && riv.altezza < H - 1) {
      const y = H - riv.altezza;
      maniglia = `<g id="r-man-riv" style="cursor:ns-resize"><line x1="0" x2="${ox - gap}" y1="${y}" y2="${y}" stroke="#a7825a" stroke-width="2" stroke-dasharray="8 5"/>
        <rect x="-4" y="${y - 11}" width="${ox - gap + 8}" height="22" fill="transparent"/>
        <text x="${ox - gap}" y="${y - 6}" text-anchor="end" font-size="13" fill="#a7825a" font-weight="600">⇕ ${Math.round(riv.altezza)} cm</text></g>`;
    }
    svgBox.innerHTML = `<svg viewBox="-6 -20 ${ox - gap + 12} ${alto + 26}" class="pareti-aperte" role="img" aria-label="Le pareti aperte con le piastrelle">
      <defs>${defs}</defs>${corpo}${maniglia}</svg>`;
    // trascina la linea del rivestimento: l'altezza si aggancia alle file intere
    const svg = svgBox.querySelector("svg"), man = svg.querySelector("#r-man-riv");
    if (man) man.addEventListener("pointerdown", (e) => {
      e.preventDefault();
      const muovi = (ev) => {
        const pt = svg.createSVGPoint(); pt.x = ev.clientX; pt.y = ev.clientY;
        const q = pt.matrixTransform(svg.getScreenCTM().inverse());
        const nuova = agganciaFila(Math.max(20, Math.min(H, H - q.y)));
        if (nuova !== superfici.rivestimento.altezza) {
          superfici.rivestimento.altezza = nuova; scelte().h_riv = nuova;
          disegnaPareti(svgBox); aggiornaConti();
        }
      };
      const fine = () => { window.removeEventListener("pointermove", muovi); window.removeEventListener("pointerup", fine); salvaSup(); };
      window.addEventListener("pointermove", muovi); window.addEventListener("pointerup", fine);
    });
  }
  let aggiornaConti = () => {};
  const salvaSup = () => api(`/api/progetti/${id}/scheda`, { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ superfici }) }).catch((e) => avviso(e.message));

  async function disegnaSuperfici() {
    if (!piastrelleCatalogo) {
      try { piastrelleCatalogo = (await api("/api/catalogo")).prodotti.filter((p) => p.tipo === "piastrella"); }
      catch (e) { piastrelleCatalogo = []; }
    }
    document.querySelectorAll("#r-stile .superfici").forEach((x) => x.remove());
    const c = scelte();
    if (!c.pav && superfici.pavimento && superfici.pavimento.piastrella) c.pav = superfici.pavimento.piastrella;
    if (!c.schema) c.schema = superfici.rivestimento || superfici.doccia ? "su_misura" : tipoStanza === "bagno" ? "classico" : "solo_pavimento";
    const box = document.createElement("div");
    box.className = "superfici";
    const sel = (nome, valore, vuoto = "— nessuna —") => `<select data-scelta-sup="${nome}"><option value="">${vuoto}</option>
      ${piastrelleCatalogo.map((p) => `<option value="${p.id}" ${valore === p.id ? "selected" : ""}>${p.nome} · ${p.foto_tipo === "superficie" ? "superficie" : `${p.larghezza}×${p.profondita}`}</option>`).join("")}</select>`;
    const pm = piastrella(c.muro);
    const rettangolare = pm && pm.foto_tipo !== "superficie" && pm.larghezza !== pm.profondita;
    box.innerHTML = `<h3 class="titolo-stanza">${NOMI_STANZA[tipoStanza]}: pavimento, rivestimenti e pareti</h3>
      ${piastrelleCatalogo.length ? "" : `<p class="sottile">Prima aggiungi nel <a href="#/catalogo">Catalogo</a> le piastrelle o le superfici (foto + misure).</p>`}
      <div class="posa-scelte">
        <label><span>1 · Pavimento</span>${sel("pav", c.pav)}</label>
        <label><span>2 · Piastrella delle pareti</span>${sel("muro", c.muro)}</label>
        <label><span>Colore delle pareti dipinte</span><input type="color" data-scelta-sup="colore" value="${c.colore || "#ebe6dd"}"></label>
        ${rettangolare ? `<label><span>Verso delle piastrelle</span><select data-scelta-sup="verso">
          <option value="orizzontale" ${c.verso !== "verticale" ? "selected" : ""}>orizzontali</option>
          <option value="verticale" ${c.verso === "verticale" ? "selected" : ""}>verticali</option></select></label>` : ""}
      </div>
      <div class="etichetta-piccola">3 · Come si posano sulle pareti</div>
      <div class="schemi">${SCHEMI.filter(([k]) => tipoStanza === "bagno" || ["solo_pavimento", "accento"].includes(k)).map(([k, nome, testo]) => `<button type="button" class="schema ${c.schema === k ? "attivo" : ""}" data-schema="${k}">
          <svg viewBox="0 0 60 44" aria-hidden="true">${ICONE_SCHEMI[k]}</svg><b>${nome}</b><small>${testo}</small></button>`).join("")}
        ${c.schema === "su_misura" ? `<div class="schema attivo"><b>Su misura</b><small>Zone cambiate a mano nei dettagli</small></div>` : ""}</div>
      ${c.schema === "accento" ? `<div class="posa-scelte">
          <label><span>Parete d'accento</span><select data-scelta-sup="parete_accento">${PARETI_ORDINE.map(([k, l]) =>
            `<option value="${k}" ${(c.parete_accento || "fondo") === k ? "selected" : ""}>Parete ${l}</option>`).join("")}</select></label>
          <label><span>Piastrella d'accento</span>${sel("accento", c.accento)}</label></div>` : ""}
      <div class="pareti-box"></div>
      <p class="sottile">Le pareti viste da dentro la stanza, in scala: le piastrelle partono intere da terra e sono centrate su ogni parete.
        ${superfici.rivestimento && superfici.rivestimento.altezza < (ultimaStanza ? ultimaStanza.H * 100 : 270) ? "Trascina la linea tratteggiata per cambiare l'altezza: si aggancia alla fila intera." : ""}</p>
      <div class="conti"></div>
      <details class="dettagli-zone"><summary>Dettagli zona per zona (per casi particolari)</summary><div class="righe-zone"></div></details>
      <button type="button" class="bottone" id="r-anteprima-sup">👁 Anteprima 3D con queste piastrelle</button>`;
    $("#r-stile").appendChild(box);
    const svgBox = box.querySelector(".pareti-box");
    aggiornaConti = () => {
      const conti = contaMetri();
      box.querySelector(".conti").innerHTML = Object.keys(conti).length ? `<div class="etichetta-piccola">Da ordinare</div>` +
        Object.entries(conti).map(([pid, m2]) => {
          const p = piastrella(pid);
          if (!p) return "";
          const prezzo = parseFloat(String(p.prezzo || "").replace(",", "."));
          return `<div class="conto"><img src="/api/catalogo/${p.id}/file/${p.foto}" alt=""><span><b>${p.nome}</b>
            ${m2.toFixed(1)} m² posati · da ordinare <b>${(m2 * 1.1).toFixed(1)} m²</b> (+10% sfrido)${prezzo && /m/.test(p.prezzo) ? ` · ≈ ${Math.round(m2 * 1.1 * prezzo)} €` : ""}</span></div>`;
        }).join("") : "";
    };
    disegnaPareti(svgBox); aggiornaConti(); righeDettaglio(box.querySelector(".righe-zone"));
    const cambia = (rifai = true) => { if (c.schema !== "su_misura") applicaSchema(); salvaSup(); if (rifai) disegnaSuperfici(); };
    box.querySelectorAll("[data-scelta-sup]").forEach((e) => e.onchange = () => {
      c[e.dataset.sceltaSup] = e.value || null;
      if (e.dataset.sceltaSup === "muro") c.h_riv = null;          // nuova piastrella: l'altezza si riaggancia alle sue file
      if (c.schema === "su_misura") {                                // su misura: si aggiornano solo pavimento e colore
        if (e.dataset.sceltaSup === "pav") superfici.pavimento = c.pav ? { piastrella: c.pav } : undefined;
        if (e.dataset.sceltaSup === "colore") superfici.pareti = { colore: c.colore };
      }
      cambia();
    });
    box.querySelectorAll("[data-schema]").forEach((b) => b.onclick = () => {
      c.schema = b.dataset.schema;
      if (!c.muro && c.schema !== "solo_pavimento" && c.schema !== "accento") mostraMessaggio("Scegli anche la piastrella delle pareti (punto 2).");
      cambia();
    });
    $("#r-anteprima-sup").onclick = faiAnteprima;
  }

  // dettagli: ogni zona a mano (diventa uno schema "su misura")
  function righeDettaglio(cont) {
    const opzioni = (spec, pittura) => `<option value="">—</option>${pittura ? `<option value="colore" ${spec.colore && !spec.piastrella ? "selected" : ""}>Pittura (tinta unita)</option>` : ""}
      ${piastrelleCatalogo.map((p) => `<option value="${p.id}" ${spec.piastrella === p.id ? "selected" : ""}>${p.nome}</option>`).join("")}`;
    cont.innerHTML = ZONE_SUP.map(([zona, nome, conAltezza, pittura]) => {
      const spec = superfici[zona] || {};
      return `<div class="sup-riga" data-zona="${zona}"><div class="sup-testo"><b>${nome}</b><div class="sup-campi">
          <select data-scelta>${opzioni(spec, pittura)}</select>
          ${spec.colore && !spec.piastrella ? `<input type="color" data-colore value="${spec.colore}">` : ""}
          ${conAltezza && (spec.piastrella || spec.colore) ? `<label>fino a <input type="number" data-altezza min="10" max="400" step="5" value="${spec.altezza || ALTEZZA_BASE[zona] || ""}"> cm</label>` : ""}
          ${spec.piastrella ? `<select data-posa>${["dritta", "sfalsata", "terzo", "diagonale"].map((x) => `<option ${(spec.posa || (piastrella(spec.piastrella) || {}).posa) === x ? "selected" : ""}>${x}</option>`).join("")}</select>` : ""}
        </div></div></div>`;
    }).join("");
    const suMisura = () => { scelte().schema = "su_misura"; salvaSup(); disegnaSuperfici(); };
    cont.querySelectorAll(".sup-riga").forEach((r) => {
      const zona = r.dataset.zona;
      r.querySelector("[data-scelta]").onchange = (e) => {
        const v = e.target.value, prima = superfici[zona] || {};
        if (!v) delete superfici[zona];
        else if (v === "colore") superfici[zona] = { colore: prima.colore || "#e2ddd4", altezza: prima.altezza };
        else superfici[zona] = { piastrella: v, altezza: prima.altezza || ALTEZZA_BASE[zona], verso: scelte().verso };
        suMisura();
      };
      const c = r.querySelector("[data-colore]");
      if (c) c.onchange = () => { superfici[zona].colore = c.value; suMisura(); };
      const a = r.querySelector("[data-altezza]");
      if (a) a.onchange = () => { superfici[zona].altezza = a.value ? +a.value : null; suMisura(); };
      const po = r.querySelector("[data-posa]");
      if (po) po.onchange = () => { superfici[zona].posa = po.value; suMisura(); };
    });
    cont.closest("details").open = scelte().schema === "su_misura";
  }

  // riepilogo (passo Genera)
  function disegnaRiepilogo() {
    const s = ultimaStanza;
    const misure = s ? `${Math.round((s.XR - s.XL) * 100)} × ${Math.round((s.ZW - s.ZB) * 100)} cm, altezza ${Math.round(s.H * 100)} cm` : "—";
    const nomiMateriali = { pavimento: "pavimento", pareti: "pareti", parete_fondo: "parete A", parete_destra: "parete B",
      parete_dietro: "parete C", parete_sinistra: "parete D", rivestimento: "rivestimento", soffitto: "soffitto",
      porte: "porte", moodboard: "moodboard" };
    const materiali = [...new Set(riferimenti.filter((r) => nomiMateriali[r.destinazione]).map((r) => nomiMateriali[r.destinazione]))];
    const righe = [
      ["Stanza", `${misureStimate() ? "≈ " : ""}${misure}`],
      ["Lavoro", NOMI_SERVIZI[servizio]],
      ...(conVarianti ? [["Disposizione", `${dati.mobili.length} mobili · variante ${dati.variante}`]] : []),
      ...(servizio === "prodotto" ? [["Prodotti", (dati.prodotti || []).filter((x) => (x.istruzione || "").trim())
        .map((x) => `«${x.istruzione}»`).join(", ") || "nessuno"]] : []),
      ["Stile", richiestaCorrente.trim() || "non indicato"],
      daPiantina
        ? ["Piastrelle", Object.keys(superfici).length ? ZONE_SUP.filter(([z]) => superfici[z]).map(([, n]) => n.toLowerCase()).join(", ")
          : "nessuna scelta (finiture neutre del programma)"]
        : ["Materiali", materiali.length ? materiali.join(", ") : "nessuna foto (li sceglie il programma)"],
    ];
    // il pulsante Genera vive dentro il riepilogo: va messo da parte prima di ridisegnarlo, se no si cancella
    const genera = $("#r-conferma");
    if (genera && $("#r-riepilogo").contains(genera)) $("#r-riepilogo").before(genera);
    $("#r-riepilogo").innerHTML = `<dl class="riepilogo">${righe.map(([k, v]) => `<div><dt>${k}</dt><dd>${v}</dd></div>`).join("")}</dl>
      <div class="genera-box" id="r-genera-box"></div>`;
    $("#r-genera-box").appendChild($("#r-conferma"));
    mostraGenera();
  }

  // cosa si vede in ogni passo
  const VISIBILE = {
    "#r-pianta": ["stanza", "disposizione"], "#r-allarme": ["stanza", "disposizione"], "#r-cosa": ["cosa"],
    "#r-arredo": daPiantina ? ["disposizione"] : ["disposizione", "stile"], "#r-stile": ["stile"], "#r-riepilogo": ["genera"],
    "#r-varianti": ["disposizione"], "#r-proposta": ["disposizione"], "#r-rapidi": ["disposizione"],
    "#r-catalogo-rilievo": ["disposizione"], "#r-parete-luci": ["disposizione"],
    "#r-azioni-arredo": servizio === "prodotto" ? ["stile"] : ["disposizione"],
    "#r-schede": ["stile"], "#r-materiali-titolo": daPiantina ? [] : ["stile"], "#r-materiali": daPiantina ? [] : ["stile"],
  };
  function vaiA(k) {
    passo = k;
    try { localStorage.setItem(CHIAVE_PASSO, k); } catch (e) { /* memoria non disponibile */ }
    Object.entries(VISIBILE).forEach(([sel, passi]) => { const e = $(sel); if (e) e.classList.toggle("fuori-passo", !passi.includes(k)); });
    const colonna = $("#r-pannello-mobili").closest(".colonna");
    const conColonna = (k === "disposizione" && conVarianti) || modoTecnico;
    colonna.classList.toggle("fuori-passo", !conColonna);
    $(".griglia-consegna").classList.toggle("senza-colonna", !conColonna);
    $("#r-conferma").classList.toggle("fuori-passo", k !== "genera");
    const [titolo, sotto] = TITOLI[k];
    $("#r-titolo").textContent = titolo;
    $("#r-intro").textContent = sotto;
    if (k === "stile") {
      $("#r-arredo-titolo").textContent = servizio === "prodotto" ? "Cosa provare" : "Materiali e prodotti veri";
      $("#r-arredo-testo").textContent = servizio === "prodotto"
        ? "Per ogni prodotto: la foto e una frase su cosa farne (es. «sostituisci il letto con questo»). Il programma trova da solo il punto nella foto."
        : "Facoltativo: trascina le foto dei materiali (pavimento, pareti, rivestimenti…) e dei prodotti veri. Senza foto li sceglie il programma in base allo stile.";
      disegnaStile();
    }
    if (k === "disposizione") {
      $("#r-arredo-titolo").textContent = "Arredo";
      $("#r-arredo-testo").textContent = `Premi ✨ Proponi arredo, oppure aggiungi i mobili con i pulsanti e clicca ${daPiantina ? "nella piantina" : "sul pavimento del 360"} dove vanno. Misure e rotazione si cambiano nell'elenco a destra.`;
    }
    if (k === "stanza" || k === "disposizione") { modoPianta = k === "stanza" ? "misure" : "arredo"; disegnaPannelloPianta(); }
    maniglie360 = false;                   // ora i pallini sono nel disegno in diretta sopra il 360
    if (daPiantina) mostra360DaPiantina();
    if (!daPiantina) {
      $("#r-viste").hidden = k !== "stanza";
      const voluta = k === "stanza" ? "linee" : "foto";
      if (vistaCorrente !== voluta && !modoTecnico) { inquadraturaLarga = voluta === "linee"; cambiaVista(voluta); }
      else disegnaPunti();                 // pallini delle pareti: solo nel passo La stanza
    }
    if (k === "cosa") disegnaCosa();
    if (k === "genera") disegnaRiepilogo();
    disegnaBarraPassi();
    window.scrollTo({ top: 0, behavior: "smooth" });
  }
  function disegnaBarraPassi() {
    const attivi = passiAttivi();
    const tutti = ["stanza", ...(daPiantina ? [] : ["cosa"]), ...(servizioScelto ? attivi.slice(daPiantina ? 1 : 2) : ["disposizione", "stile", "genera"])];
    const i = tutti.indexOf(passo);
    $("#r-passi").innerHTML = `<span class="passo-barra fatto">1 · Carica ✓</span>` + tutti.map((k, n) => {
      const ok = attivi.includes(k);
      return `<button type="button" class="passo-barra ${k === passo ? "attivo" : n < i ? "fatto" : ""}" data-passo="${k}" ${ok ? "" : "disabled"}>${n + 2} · ${NOMI_PASSI[k]}</button>`;
    }).join("");
    document.querySelectorAll("#r-passi [data-passo]").forEach((b) => b.onclick = () => vaiA(b.dataset.passo));
    const prec = attivi[attivi.indexOf(passo) - 1], succ = attivi[attivi.indexOf(passo) + 1];
    $("#r-nav").innerHTML = `${prec ? `<button type="button" class="bottone" data-vai="${prec}">← ${NOMI_PASSI[prec]}</button>` : "<span></span>"}
      ${succ ? `<button type="button" class="bottone primario" data-vai="${succ}">Avanti: ${NOMI_PASSI[succ]} →</button>`
        : passo === "cosa" && !servizioScelto ? `<span class="sottile">Scegli una delle tre strade per continuare.</span>` : ""}`;
    document.querySelectorAll("#r-nav [data-vai]").forEach((b) => b.onclick = () => vaiA(b.dataset.vai));
  }
  vaiA(passo);


  // ---- LINEE DELLA STANZA IN DIRETTA SUL 360 (passo "La stanza", progetti da foto)
  // Le linee (pavimento, soffitto, angoli) si disegnano sopra il 360 a ogni fotogramma, così seguono la vista.
  // Pallini: angoli e metà parete IN BASSO e IN ALTO. Regola unica: ogni pallino va messo sul punto vero.
  //   basso (angoli e metà parete) -> pareti, sul pavimento; alto agli angoli -> pareti, sul soffitto
  //   (utile quando in basso i mobili coprono); alto a metà parete -> altezza del soffitto.
  const tela = document.createElement("canvas");
  tela.className = "linee-live";
  $("#r-contenitore").appendChild(tela);
  let bozza = null, trascino = null;
  const lineeAttive = () => !daPiantina && passo === "stanza" && vistaCorrente === "linee" && vista && vista.isLoaded() && ultimaStanza;

  function proietta(s, X, y, Z, W, H, cam) {          // punto della stanza -> pixel sullo schermo
    const [yaw, pitch] = versoMondo(s, X, y, Z);
    const yr = rad(yaw), pr = rad(pitch);
    const x = Math.cos(pr) * Math.sin(yr), yy = Math.sin(pr), z = Math.cos(pr) * Math.cos(yr);
    const x1 = x * cam.cy - z * cam.sy, z1 = x * cam.sy + z * cam.cy;
    const y2 = yy * cam.cp - z1 * cam.sp, z2 = yy * cam.sp + z1 * cam.cp;
    if (z2 < 0.02) return null;
    return [W / 2 + cam.f * x1 / z2, H / 2 - cam.f * y2 / z2];
  }
  function maniglie(s) {
    const yp = -s.h, ys = s.H - s.h, mx = (s.XL + s.XR) / 2, mz = (s.ZB + s.ZW) / 2;
    const angoli = [["XL", "ZB"], ["XR", "ZB"], ["XR", "ZW"], ["XL", "ZW"]];
    const pareti = [["XL", s.XL, mz], ["XR", s.XR, mz], ["ZB", mx, s.ZB], ["ZW", mx, s.ZW]];
    return [
      ...angoli.map(([a, b]) => ({ tipo: "angolo", piano: "pavimento", k: [a, b], p: [s[a], yp, s[b]] })),
      ...pareti.map(([k, x, z]) => ({ tipo: "parete", piano: "pavimento", k: [k], p: [x, yp, z] })),
      ...angoli.map(([a, b]) => ({ tipo: "angolo", piano: "soffitto", k: [a, b], p: [s[a], ys, s[b]] })),
      ...pareti.map(([k, x, z]) => ({ tipo: "altezza", piano: "soffitto", k: [k], p: [x, ys, z] })),
    ];
  }
  function camera() {
    const W = tela.clientWidth, H = tela.clientHeight;
    const vy = rad(vista.getYaw()), vp = rad(vista.getPitch());
    return { W, H, cam: { f: (W / 2) / Math.tan(rad(vista.getHfov()) / 2), cy: Math.cos(vy), sy: Math.sin(vy), cp: Math.cos(vp), sp: Math.sin(vp) } };
  }
  function disegnaLinee() {
    const dpr = window.devicePixelRatio || 1;
    const W = tela.clientWidth, H = tela.clientHeight;
    if (tela.width !== Math.round(W * dpr) || tela.height !== Math.round(H * dpr)) { tela.width = Math.round(W * dpr); tela.height = Math.round(H * dpr); }
    const ctx = tela.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, W, H);
    if (!lineeAttive()) return;
    const s = bozza || ultimaStanza, { cam } = camera();
    const yp = -s.h, ys = s.H - s.h;
    const angoli = [[s.XL, s.ZB], [s.XR, s.ZB], [s.XR, s.ZW], [s.XL, s.ZW]];
    const segmenti = [];
    for (let i = 0; i < 4; i++) {
      const [a, b] = [angoli[i], angoli[(i + 1) % 4]];
      segmenti.push([[a[0], yp, a[1]], [b[0], yp, b[1]]], [[a[0], ys, a[1]], [b[0], ys, b[1]]]);
      segmenti.push([[a[0], yp, a[1]], [a[0], ys, a[1]]]);
    }
    const tratto = (larghezza, colore) => {
      ctx.lineWidth = larghezza; ctx.strokeStyle = colore; ctx.lineJoin = "round"; ctx.lineCap = "round";
      segmenti.forEach(([p, q]) => {
        ctx.beginPath();
        let su = false;
        for (let i = 0; i <= 48; i++) {
          const t = i / 48;
          const pt = proietta(s, p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t, p[2] + (q[2] - p[2]) * t, W, H, cam);
          if (!pt || Math.abs(pt[0]) > W * 4 || Math.abs(pt[1]) > H * 4) { su = false; continue; }
          if (su) ctx.lineTo(pt[0], pt[1]); else { ctx.moveTo(pt[0], pt[1]); su = true; }
        }
        ctx.stroke();
      });
    };
    tratto(5, "rgba(0,0,0,.35)");
    tratto(2.5, "#e3b341");
    maniglie(s).forEach((m) => {
      const pt = proietta(s, ...m.p, W, H, cam);
      if (!pt || pt[0] < -20 || pt[0] > W + 20 || pt[1] < -20 || pt[1] > H + 20) return;
      const attiva = trascino && trascino.m.tipo === m.tipo && trascino.m.piano === m.piano && trascino.m.k.join() === m.k.join();
      ctx.beginPath();
      ctx.arc(pt[0], pt[1], attiva ? 12 : 9, 0, Math.PI * 2);
      ctx.fillStyle = m.tipo === "angolo" ? "#fff" : "#e3b341";
      ctx.strokeStyle = m.tipo === "angolo" ? "#e3b341" : "#fff";
      ctx.lineWidth = 3.5;
      ctx.shadowColor = "rgba(0,0,0,.5)"; ctx.shadowBlur = 6;
      ctx.fill(); ctx.stroke();
      ctx.shadowBlur = 0;
    });
  }
  (function ciclo() {
    if (!tela.isConnected) return;               // pagina cambiata: il ciclo si ferma
    disegnaLinee();
    requestAnimationFrame(ciclo);
  })();

  function manigliaVicina(e) {
    if (!lineeAttive()) return null;
    const r = tela.getBoundingClientRect(), x = e.clientX - r.left, y = e.clientY - r.top;
    const s = ultimaStanza, { W, H, cam } = camera();
    let migliore = null;
    maniglie(s).forEach((m) => {
      const pt = proietta(s, ...m.p, W, H, cam);
      if (!pt) return;
      const d = Math.hypot(pt[0] - x, pt[1] - y);
      if (d < 24 && (!migliore || d < migliore.d)) migliore = { m, d };
    });
    return migliore && migliore.m;
  }
  const contenitoreLinee = $("#r-contenitore");
  contenitoreLinee.addEventListener("pointerdown", (e) => {
    const m = manigliaVicina(e);
    if (!m) return;
    trascino = { m };
    bozza = { ...ultimaStanza };
    e.preventDefault(); e.stopPropagation();       // il 360 non deve girare mentre si sposta un pallino
  }, true);
  ["mousedown", "touchstart"].forEach((ev) => contenitoreLinee.addEventListener(ev, (e) => {
    if (trascino) { e.preventDefault(); e.stopPropagation(); }
  }, { capture: true, passive: false }));
  window.addEventListener("pointermove", (e) => {
    if (!trascino) {
      if (lineeAttive()) contenitoreLinee.style.cursor = manigliaVicina(e) ? "grab" : "";
      return;
    }
    e.preventDefault();
    const [pitch, yaw] = vista.mouseEventToCoords(e);
    const s = bozza, d = versoStanza(s, yaw, pitch), m = trascino.m;
    const prova = { ...s };
    if (m.tipo === "altezza") {
      // la linea del soffitto su quella parete va dove la metti: cambia l'altezza, le pareti restano
      const asse = m.k[0][0] === "X" ? 0 : 2;
      if (Math.abs(d[asse]) < 1e-3) return;
      const t = s[m.k[0]] / d[asse];
      if (t <= 0) return;
      prova.H = s.h + t * d[1];
    } else {
      const quota = m.piano === "pavimento" ? -s.h : s.H - s.h;
      if (m.piano === "pavimento" ? d[1] > -0.02 : d[1] < 0.02) return;
      const t = quota / d[1];
      const X = t * d[0], Z = t * d[2];
      m.k.forEach((k) => { prova[k] = k[0] === "X" ? X : Z; });
    }
    if (prova.XL < -0.2 && prova.XR > 0.2 && prova.ZB < -0.2 && prova.ZW > 0.2 && prova.H > s.h + 0.3 && prova.H < 8) bozza = prova;
  }, { passive: false });
  window.addEventListener("pointerup", () => {
    if (!trascino) return;
    const cambiataAltezza = trascino.m.tipo === "altezza";
    trascino = null;
    let b = bozza;
    bozza = null;
    if (!b) return;
    // se le misure sono solo stimate, la scala resta "soffitto a 2,70 m": spostare la linea del soffitto
    // cambia il rapporto fotocamera/soffitto, poi tutta la stanza si riporta a quella scala
    if (cambiataAltezza && misureStimate()) {
      const k = 2.70 / b.H;
      b = { ...b, h: b.h * k, XL: b.XL * k, XR: b.XR * k, ZB: b.ZB * k, ZW: b.ZW * k, H: 2.70 };
    }
    dati.scatola = { h: b.h, theta: b.theta, XL: b.XL, XR: b.XR, ZB: b.ZB, ZW: b.ZW, H: b.H };
    dati.altezza_camera = +b.h.toFixed(3); $("#r-altezza").value = dati.altezza_camera;
    dati.tara_soffitto = false;
    delete dati.misura_vera;
    ultimaStanza = { ...ultimaStanza, ...b };      // si vede subito, poi arriva il calcolo del server
    disegnaSvg();
    aggiornaModello();
  });

  // il viewer l'ha già aperto il passo corrente (foto o linee delle pareti); se no si apre la foto
  if (!vista) caricaViewer();
  if (dati.angoli.length + dati.spigoli.length >= 3) salva();
}

// ------------------------------------------------------------ CASA INTERA: scegli le stanze con un clic

async function paginaCasa(cid) {
  pulisci();
  let casa = await api(`/api/case/${cid}`);
  if (casa.stato === "lettura") {
    pagina.innerHTML = `<section class="intestazione"><h1>Leggo la piantina…</h1>
      <p>Claude trova tutte le stanze con le loro misure, porte e finestre. Circa 30-60 secondi.</p></section>
      <div class="pannello stato-live"><div class="spinner-grande"></div><div class="testo-live">${casa.messaggio || ""}</div></div>`;
    timerAttivi.push(setInterval(async () => {
      const c = await api(`/api/case/${cid}`);
      if (c.stato !== "lettura") naviga();
    }, 2000));
    return;
  }
  if (casa.stato === "errore") {
    pagina.innerHTML = `<section class="intestazione"><h1>Piantina non letta</h1><p>${casa.messaggio}</p></section>
      <a class="bottone primario" href="#/nuovo">Riprova con un'altra piantina</a>`;
    return;
  }
  const scelte = new Set();
  const creati = casa.progetti || {};
  pagina.innerHTML = `<section class="intestazione intestazione-consegna">
      <div><div class="sovratitolo sovratitolo-accento"><span class="punto-accento"></span>Piantina della casa · ${casa.stanze.length} stanze</div>
        <h1>Scegli le stanze da lavorare</h1>
        <p class="richiesta-citata">Clicca una o più stanze sulla piantina (o nell'elenco). Ognuna diventa un progetto, e potrai passare dall'una all'altra.</p></div>
      <div class="azioni"><button class="bottone primario" id="casa-crea" disabled>Crea i progetti →</button></div>
    </section>
    <div class="griglia-casa">
      <div class="pannello casa-pianta">${casa.immagine
        ? `<div class="casa-immagine"><img src="/api/case/${cid}/file/${casa.piantina}" alt="Piantina">
            ${casa.stanze.map((s, i) => { const [x0, y0, x1, y1] = s.riquadro;
              return `<button type="button" class="casa-vano" data-i="${i}" title="${s.nome}"
                style="left:${x0 / 10}%;top:${y0 / 10}%;width:${(x1 - x0) / 10}%;height:${(y1 - y0) / 10}%">
                <span>${s.nome}</span></button>`; }).join("")}</div>`
        : `<p class="sottile">La piantina è un PDF: scegli le stanze dall'elenco qui accanto.
            <a href="/api/case/${cid}/file/${casa.piantina}" target="_blank">Apri la piantina</a></p>`}</div>
      <div class="pannello casa-elenco">
        ${casa.stanze.map((s, i) => `<label class="casa-riga" data-riga="${i}">
            <input type="checkbox" data-scegli="${i}">
            <span><strong>${s.nome}</strong><small>${s.larghezza} × ${s.profondita} cm · ${(s.larghezza * s.profondita / 10000).toFixed(1)} m²
              · ${s.aperture.length} aperture</small>${s.note ? `<small class="sottile">${s.note}</small>` : ""}</span>
            ${creati[i] ? `<a class="chip ok" href="#/rilievo/${creati[i]}">✓ già creata · apri</a>` : ""}
          </label>`).join("")}
        ${casa.note ? `<p class="sottile">${casa.note}</p>` : ""}
      </div>
    </div>`;
  function aggiorna() {
    document.querySelectorAll("[data-scegli]").forEach((c) => { c.checked = scelte.has(+c.dataset.scegli); });
    document.querySelectorAll(".casa-vano").forEach((v) => v.classList.toggle("scelto", scelte.has(+v.dataset.i)));
    document.querySelectorAll(".casa-riga").forEach((r) => r.classList.toggle("scelto", scelte.has(+r.dataset.riga)));
    $("#casa-crea").disabled = !scelte.size;
    $("#casa-crea").textContent = scelte.size ? `Crea ${scelte.size === 1 ? "il progetto" : `${scelte.size} progetti`} →` : "Crea i progetti →";
  }
  const cambia = (i) => { if (scelte.has(i)) scelte.delete(i); else scelte.add(i); aggiorna(); };
  document.querySelectorAll(".casa-vano").forEach((v) => v.onclick = () => cambia(+v.dataset.i));
  document.querySelectorAll("[data-scegli]").forEach((c) => c.onchange = () => cambia(+c.dataset.scegli));
  $("#casa-crea").onclick = async () => {
    $("#casa-crea").disabled = true; $("#casa-crea").textContent = "Creo i progetti…";
    try {
      const r = await api(`/api/case/${cid}/stanze`, { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ indici: [...scelte].sort((a, b) => a - b) }) });
      location.hash = `#/rilievo/${r.progetti[0]}`;
    } catch (e) { mostraMessaggio(e.message); aggiorna(); }
  };
  aggiorna();
}

// ------------------------------------------------------------ CATALOGO DELL'IMPRESA

async function paginaCatalogo() {
  mostra("#t-catalogo");
  let dati = await api("/api/catalogo");
  $("#cat-categoria").innerHTML = dati.categorie.filter((c) => c !== "Piastrella").map((c) => `<option>${c}</option>`).join("");
  $("#cat-finitura").innerHTML = dati.finiture.map((c) => `<option>${c}</option>`).join("");
  $("#cat-posa").innerHTML = dati.pose.map((c) => `<option>${c}</option>`).join("");
  const modulo = $("#cat-modulo");
  // Prodotto 3D oppure Piastrella: lo stesso modulo cambia campi e spiegazioni
  function tipoModulo(tipo) {
    modulo.elements.tipo.value = tipo;
    document.querySelectorAll("#cat-tipo [data-tipo]").forEach((b) => b.classList.toggle("attivo", b.dataset.tipo === tipo));
    modulo.querySelectorAll("[data-solo]").forEach((e) => { e.hidden = e.dataset.solo !== tipo; });
    const piastrella = tipo === "piastrella";
    modulo.querySelector('[data-etichetta="larghezza"]').textContent = piastrella ? "Formato: lato 1" : "Larghezza";
    modulo.querySelector('[data-etichetta="profondita"]').textContent = piastrella ? "Lato 2" : "Profondità";
    modulo.querySelector('[data-etichetta="altezza"]').textContent = piastrella ? "Spessore" : "Altezza";
    modulo.querySelector('[data-etichetta="foto"]').textContent = piastrella ? "Foto della piastrella" : "Foto del prodotto";
    modulo.elements.nome.placeholder = piastrella ? "Es. Marmo Botticino 60×60 levigato" : "Es. Vasca freestanding Ovale 170";
    $("#cat-nome-foto").textContent = piastrella ? "La superficie dritta, senza ombre né riflessi (anche la texture del produttore)"
      : "JPG o PNG, su sfondo il più possibile neutro";
    $("#cat-spiega-misure").textContent = piastrella
      ? "Il formato vero (es. 60 × 60 o 30 × 60): la piastrella viene posata in scala reale, con le fughe e la posa scelte."
      : "Le misure vere del prodotto (dalla scheda tecnica): il modello 3D viene portato esattamente a queste misure. «Da terra» serve per i prodotti sospesi.";
    if (piastrella && !modulo.elements.altezza.value) modulo.elements.altezza.value = 1;
    tipoFoto();
  }
  // piastrella sola o superficie già posata: cambiano le misure richieste e spariscono fuga e posa
  function tipoFoto() {
    const superficie = modulo.elements.tipo.value === "piastrella" && modulo.elements.foto_tipo.value === "superficie";
    modulo.querySelectorAll("[data-solo-foto]").forEach((e) => { e.hidden = superficie; });
    if (modulo.elements.tipo.value !== "piastrella") return;
    modulo.querySelector('[data-etichetta="larghezza"]').textContent = superficie ? "La foto copre: larghezza" : "Formato: lato 1";
    modulo.querySelector('[data-etichetta="profondita"]').textContent = superficie ? "altezza" : "Lato 2";
    $("#cat-spiega-misure").textContent = superficie
      ? "Quanto è grande nella realtà il pezzo di pavimento della foto. Es. 5 doghe larghe 20 cm = 100 cm. Spesso è scritto sul sito del produttore; se non lo sai conta le doghe e moltiplica per la loro larghezza."
      : "Il formato vero (es. 60 × 60 o 30 × 60): la piastrella viene posata in scala reale, con le fughe e la posa scelte.";
  }
  modulo.querySelectorAll('[name="foto_tipo"]').forEach((r) => r.onchange = tipoFoto);
  document.querySelectorAll("#cat-tipo [data-tipo]").forEach((b) => b.onclick = () => tipoModulo(b.dataset.tipo));
  // luci e specchi: campi in più, e le misure spiegate per loro
  function categoriaModulo() {
    const cat = modulo.elements.tipo.value === "prodotto" ? $("#cat-categoria").value : "";
    modulo.querySelectorAll("[data-solo-cat]").forEach((e) => { e.hidden = e.dataset.soloCat !== cat; });
    // lampade: spesso il sito dà solo il diametro -> profondità e altezza diventano facoltative
    const luce = cat === "Illuminazione";
    modulo.elements.profondita.required = modulo.elements.altezza.required = !luce;
    if (modulo.elements.tipo.value === "prodotto")
      modulo.querySelector('[data-etichetta="larghezza"]').textContent = luce ? "Larghezza o diametro" : "Larghezza";
    modulo.elements.profondita.placeholder = luce ? "= diametro" : "";
    modulo.elements.altezza.placeholder = luce ? "automatica" : "";
    if (luce) $("#cat-spiega-misure").textContent =
      "Se il sito dà solo il diametro (es. 40 cm) scrivi solo quello: la profondità diventa uguale e l'altezza la mette il programma " +
      "(faretto 2 cm, plafoniera 6, sospensione 25, applique 20). Per le sospensioni la «Calata» è quanto scende dal soffitto.";
    else if (cat === "Specchio") $("#cat-spiega-misure").textContent =
      "Larghezza e altezza dello specchio, profondità = spessore (2-4 cm). «Da terra»: di solito 105-110 cm sopra un lavabo.";
  }
  $("#cat-categoria").addEventListener("change", categoriaModulo);
  modulo.elements.nome.addEventListener("input", () => {
    const n = modulo.elements.nome.value.toLowerCase();
    const tipo = /plafonier/.test(n) ? "plafoniera" : /sospension|pendent|lampadari/.test(n) ? "sospensione"
      : /applique|lampada da parete/.test(n) ? "applique" : /farett|spot/.test(n) ? "faretto" : null;
    if (tipo && $("#cat-categoria").value === "Illuminazione") modulo.elements.tipo_luce.value = tipo;
  });
  document.querySelectorAll("#cat-tipo [data-tipo]").forEach((b) => b.addEventListener("click", categoriaModulo));
  // nome del file scelto, così si vede che è stato preso
  [["foto", "#cat-nome-foto"], ["modello", "#cat-nome-modello"]].forEach(([campo, etichetta]) => {
    modulo.elements[campo].addEventListener("change", () => {
      const f = modulo.elements[campo].files[0];
      if (f) $(etichetta).textContent = `✓ ${f.name}`;
    });
  });

  const STATI = { pronto: ["ok", "✓ Modello 3D pronto"], in_creazione: ["", "Meshy sta creando il 3D…"],
    errore: ["errore", "Errore"], nessuno: ["", "Solo misure: forma a misura nel render"] };
  function disegna() {
    $("#cat-conta").textContent = `${dati.prodotti.length} prodott${dati.prodotti.length === 1 ? "o" : "i"}`;
    $("#cat-meshy").hidden = dati.meshy;
    $("#cat-meshy").innerHTML = "Per creare il modello 3D dalla foto serve la chiave di <b>Meshy</b>: aggiungi la riga " +
      "<code>MESHY_API_KEY=...</code> nel file <code>.env</code> e riavvia il programma.";
    $("#cat-lista").innerHTML = dati.prodotti.map((p) => {
      const [classe, testo] = STATI[p.stato_modello] || STATI.nessuno;
      const img = p.anteprima ? `<img src="/api/catalogo/${p.id}/file/${p.anteprima}?v=${Date.now()}" alt="">` : `<div class="cat-vuota">📦</div>`;
      const progresso = p.stato_modello === "in_creazione" ? ` ${p.avanzamento || 0}%` : "";
      return `<article class="cat-scheda" data-id="${p.id}">
        <button type="button" class="cat-img" data-apri="${p.id}" title="Apri la scheda">${img}</button>
        <div class="cat-info">
          <button type="button" class="cat-nome" data-apri="${p.id}">${p.nome}</button>
          <span class="sottile">${p.tipo === "piastrella"
            ? (p.foto_tipo === "superficie" ? `Superficie posata · la foto copre ${p.larghezza} × ${p.profondita} cm · ${p.finitura}`
              : `Piastrella ${p.larghezza} × ${p.profondita} cm · ${p.finitura} · fuga ${p.fuga_mm} mm · posa ${p.posa}`)
            : `${p.categoria} · ${p.larghezza} × ${p.profondita} × h ${p.altezza} cm${p.quota ? ` · da terra ${p.quota} cm` : ""}`}</span>
          ${p.fornitore || p.codice || p.prezzo ? `<span class="sottile">${[p.fornitore, p.codice, p.prezzo].filter(Boolean).join(" · ")}</span>` : ""}
          ${p.tipo === "piastrella" ? `<span class="chip ok">✓ Pronta per la posa</span>` : `<span class="chip ${classe}">${testo}${progresso}</span>`}
          ${avvisoProporzioni(p).includes("⚠") ? `<span class="chip errore" data-apri="${p.id}" style="cursor:pointer">⚠ Controlla le misure</span>` : ""}
          ${p.stato_modello === "errore" ? `<span class="errore">${p.messaggio}</span>` : ""}
          <div class="cat-azioni">
            ${p.tipo !== "piastrella" && p.foto && p.stato_modello !== "pronto" && p.stato_modello !== "in_creazione"
              ? `<button type="button" class="bottone piccolo primario" data-meshy="${p.id}">✨ Crea il modello 3D dalla foto</button>` : ""}
            ${p.tipo === "piastrella" ? "" : `<label class="bottone piccolo">🧊 ${p.stato_modello === "pronto" ? "Sostituisci il modello 3D" : "Carica il modello 3D"}
              <input type="file" accept=".glb,.gltf,.obj,.fbx" data-modello="${p.id}" hidden></label>`}
            ${p.stato_modello === "pronto" ? `<select data-rot="${p.id}" title="Se il prodotto appare girato nel render">
              ${[0, 90, 180, 270].map((r) => `<option value="${r}" ${+p.rotazione_modello === r ? "selected" : ""}>giro ${r}°</option>`).join("")}</select>` : ""}
            <button type="button" class="bottone piccolo" data-apri="${p.id}">✏️ Scheda e misure</button>
            <button type="button" class="togli-mobile" data-togli="${p.id}">🗑 Togli</button>
          </div>
        </div>
      </article>`;
    }).join("") || `<p class="sottile">Ancora nessun prodotto: aggiungi il primo con il modulo a sinistra.</p>`;

    document.querySelectorAll("[data-meshy]").forEach((b) => b.onclick = async () => {
      if (!(await chiediConferma("Creo il modello 3D dalla foto con Meshy?",
        "Meshy trasforma la foto in un oggetto 3D (circa 1-3 minuti). Consuma crediti del tuo piano Meshy (circa 30 a modello; i tentativi falliti sono rimborsati).",
        "Crea"))) return;
      try { await api(`/api/catalogo/${b.dataset.meshy}/meshy`, { method: "POST" }); } catch (e) { mostraMessaggio(e.message); }
      aggiorna();
    });
    document.querySelectorAll("[data-modello]").forEach((inp) => inp.onchange = async () => {
      const f = inp.files[0];
      if (!f) return;
      const corpo = new FormData(); corpo.append("modello", f);
      try { await api(`/api/catalogo/${inp.dataset.modello}/modello`, { method: "POST", body: corpo }); mostraMessaggio("Modello 3D caricato.", "ok"); }
      catch (e) { mostraMessaggio(e.message); }
      aggiorna();
    });
    document.querySelectorAll("[data-rot]").forEach((s) => s.onchange = async () => {
      await api(`/api/catalogo/${s.dataset.rot}/modifica`, { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ rotazione_modello: +s.value }) });
      aggiorna();
    });
    document.querySelectorAll("[data-apri]").forEach((b) => b.onclick = () =>
      apriScheda(dati.prodotti.find((p) => p.id === b.dataset.apri)));
    document.querySelectorAll("[data-togli]").forEach((b) => b.onclick = async () => {
      if (!(await chiediConferma("Tolgo il prodotto dal catalogo?", "Foto e modello 3D di questo prodotto vengono eliminati.", "Togli"))) return;
      await api(`/api/catalogo/${b.dataset.togli}`, { method: "DELETE" });
      aggiorna();
    });
  }
  async function aggiorna() { dati = await api("/api/catalogo"); disegna(); }

  // SCHEDA PRODOTTO: il modello 3D da girare col mouse + tutte le misure e i dati modificabili
  const MISURE_TIPICHE = {
    Vasca: "Freestanding: 160-180 × 70-80 cm, alta 55-60 cm. Da incasso: 170 × 70, alta 50-55.",
    Doccia: "Piatto: 80×80, 90×90, 70×120, 80×140, 90×160 cm, spessore 3 cm.",
    Sanitari: "WC/bidet sospesi: larghi 35-38, profondi 50-55, seduta a 40 cm da terra.",
    "Mobile bagno": "Larghi 60-120, profondi 45-50, alti 50-60; sospesi con il top a 85 cm da terra.",
    Termoarredo: "Larghi 50-60, alti 120-180, profondi 8-10 cm.",
    Letto: "Matrimoniale 160×200 (ingombro circa 175×215), alto 90-110 alla testiera.",
    Divano: "3 posti: 200-230 × 90-100, alto 80-90 cm.",
    Tavolo: "Alto 75 cm; 4 persone 120×80, 6 persone 160-180×90.",
  };
  // confronto tra le misure della scheda e le proporzioni vere del modello 3D
  function avvisoProporzioni(p) {
    const m = p.proporzioni_modello;
    if (!m || m.length !== 3 || p.tipo === "piastrella") return "";
    const [dx, dz, dy] = m;
    const P = Math.round(p.larghezza * dz / dx), A = Math.round(p.larghezza * dy / dx);
    const righe = [`🧊 Nel render, in proporzione: <b>${p.larghezza} × ${P} × h ${A} cm</b> (larghezza × profondità × altezza).`];
    if ((p.larghezza > p.profondita * 1.15 && dz > dx * 1.15) || (p.profondita > p.larghezza * 1.15 && dx > dz * 1.15)) {
      righe.push(`⚠ <b>Larghezza e profondità sembrano invertite</b> rispetto al modello 3D: nel modello il lato lungo è
        ${dx > dz ? "la larghezza" : "la profondità"}. La larghezza è il lato che vedi stando di fronte al prodotto.`);
    } else if (Math.abs(P - p.profondita) > p.profondita * 0.25 || Math.abs(A - p.altezza) > p.altezza * 0.25) {
      righe.push(`⚠ Il modello ha proporzioni diverse dalla scheda (${p.profondita} × h ${p.altezza}): forse comprende anche
        rubinetto, specchio o piedini, oppure le misure non sono quelle vere. Se il file è del produttore scegli «stirato sulle 3 misure».`);
    }
    return `<p class="suggerimento ${righe.length > 1 ? "attenzione" : ""}">${righe.join("<br>")}</p>`;
  }
  function apriScheda(p) {
    if (!p) return;
    const piastrella = p.tipo === "piastrella";
    const glb = p.modello && p.stato_modello === "pronto" && /\.(glb|gltf)$/i.test(p.modello);
    const vista = glb
      ? `<model-viewer src="/api/catalogo/${p.id}/file/${p.modello}?v=${Date.now()}" camera-controls auto-rotate
           shadow-intensity="0.8" exposure="1" alt="${p.nome}"></model-viewer>
         <p class="sottile">Trascina per girarlo, rotellina per avvicinarti.</p>`
      : `${p.foto ? `<img src="/api/catalogo/${p.id}/file/${p.anteprima || p.foto}" alt="">` : `<div class="cat-vuota">📦</div>`}
         <p class="sottile">${piastrella ? "La foto viene posata in scala reale." : p.modello ? "Anteprima 3D disponibile solo per i file GLB/GLTF." : "Nessun modello 3D: nel render una forma a misura."}</p>`;
    const campo = (k, etichetta) =>
      `<label>${etichetta}<input name="${k}" type="text" value="${String(p[k] ?? "").replace(/"/g, "&quot;")}"></label>`;
    const num = (k, etichetta, unita = "cm") =>
      `<label>${etichetta}<span><input name="${k}" type="number" min="0" value="${p[k] ?? 0}"> ${unita}</span></label>`;
    const sfondo = document.createElement("div");
    sfondo.className = "modale-sfondo";
    sfondo.innerHTML = `<div class="modale scheda-prodotto">
      <button type="button" class="chiudi" data-chiudi aria-label="Chiudi">✕</button>
      <div class="sp-vista">${vista}</div>
      <form class="sp-dati colonna">
        <h2>${p.nome}</h2>
        ${campo("nome", "Nome")}
        ${piastrella ? "" : `<label>Categoria<select name="categoria">${dati.categorie.filter((c) => c !== "Piastrella")
          .map((c) => `<option ${c === p.categoria ? "selected" : ""}>${c}</option>`).join("")}</select></label>`}
        <div class="cat-misure">
          ${num("larghezza", piastrella ? "Lato 1" : "Larghezza")}${num("profondita", piastrella ? "Lato 2" : "Profondità")}
          ${num("altezza", piastrella ? "Spessore" : "Altezza")}${piastrella ? "" : num("quota", "Da terra")}
        </div>
        ${avvisoProporzioni(p)}
        ${p.categoria === "Illuminazione" ? `<div class="cat-misure">
            <label>Tipo di luce<select name="tipo_luce">${[["faretto", "faretto a incasso"], ["plafoniera", "plafoniera"],
              ["sospensione", "lampada a sospensione"], ["applique", "applique (a parete)"]].map(([v, n]) =>
              `<option value="${v}" ${(p.tipo_luce || "faretto") === v ? "selected" : ""}>${n}</option>`).join("")}</select></label>
            <label>Luce<select name="k">${[[2700, "molto calda 2700 K"], [3000, "calda 3000 K"], [4000, "naturale 4000 K"]].map(([v, n]) =>
              `<option value="${v}" ${+(p.k || 3000) === v ? "selected" : ""}>${n}</option>`).join("")}</select></label>
            ${num("calata", "Calata (sospensioni)")}</div>` : ""}
        ${p.categoria === "Specchio" ? `<label>Luce dello specchio<select name="luce_specchio">${[["", "nessuna"],
          ["sopra", "lampada sopra lo specchio"], ["dietro", "retroilluminato (LED dietro)"]].map(([v, n]) =>
          `<option value="${v}" ${(p.luce_specchio || (p.led ? "dietro" : "")) === v ? "selected" : ""}>${n}</option>`).join("")}</select></label>` : ""}
        ${MISURE_TIPICHE[p.categoria] ? `<p class="suggerimento">📏 Misure tipiche — ${MISURE_TIPICHE[p.categoria]}
          Le misure vere sono nella scheda tecnica del produttore (sito o catalogo, voce "dimensioni").</p>` : ""}
        ${piastrella ? `<label>La foto mostra<select name="foto_tipo">
            <option value="piastrella" ${p.foto_tipo !== "superficie" ? "selected" : ""}>una piastrella sola (larghezza × profondità = formato)</option>
            <option value="superficie" ${p.foto_tipo === "superficie" ? "selected" : ""}>una superficie già posata (misure = quanto copre la foto)</option>
          </select></label>` : ""}
        ${piastrella ? `<div class="cat-misure">
            <label>Finitura<select name="finitura">${dati.finiture.map((x) => `<option ${x === p.finitura ? "selected" : ""}>${x}</option>`).join("")}</select></label>
            ${num("fuga_mm", "Fuga", "mm")}
            <label>Colore fuga<input name="fuga_colore" type="color" value="${p.fuga_colore}"></label>
            <label>Posa<select name="posa">${dati.pose.map((x) => `<option ${x === p.posa ? "selected" : ""}>${x}</option>`).join("")}</select></label>
          </div>` : p.modello ? `<div class="cat-misure">
            <label>Il modello 3D nel render<select name="scala_modello">
              <option value="proporzioni" ${p.scala_modello !== "esatte" ? "selected" : ""}>in proporzione dalla larghezza (consigliato da foto)</option>
              <option value="esatte" ${p.scala_modello === "esatte" ? "selected" : ""}>stirato sulle 3 misure (file del produttore)</option></select></label>
            <label>Rotazione<select name="rotazione_modello">${[0, 90, 180, 270].map((r) =>
              `<option value="${r}" ${+p.rotazione_modello === r ? "selected" : ""}>giro ${r}°</option>`).join("")}</select></label>
          </div>` : ""}
        <details ${p.fornitore || p.codice || p.prezzo ? "open" : ""}><summary>Dati commerciali</summary>
          ${campo("fornitore", "Fornitore")}${campo("codice", "Codice")}${campo("prezzo", "Prezzo")}${campo("nota", "Nota")}
        </details>
        <p class="errore" hidden></p>
        <div class="azioni"><button type="button" class="bottone" data-chiudi>Chiudi</button>
          <button type="submit" class="bottone primario">Salva le modifiche</button></div>
      </form></div>`;
    const chiudi = () => sfondo.remove();
    sfondo.addEventListener("click", (e) => { if (e.target === sfondo || e.target.closest("[data-chiudi]")) chiudi(); });
    const form = sfondo.querySelector("form");
    form.onsubmit = async (e) => {
      e.preventDefault();
      const campi = Object.fromEntries(new FormData(form).entries());
      if (p.categoria === "Specchio") campi.led = campi.luce_specchio === "dietro" ? "1" : "";
      try {
        await api(`/api/catalogo/${p.id}/modifica`, { method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify(campi) });
        chiudi();
        mostraMessaggio("Modifiche salvate: valgono dal prossimo render e dalla prossima anteprima.", "ok");
        aggiorna();
      } catch (err) { const x = form.querySelector(".errore"); x.textContent = err.message; x.hidden = false; }
    };
    document.body.appendChild(sfondo);
  }
  // mentre Meshy lavora la pagina si aggiorna da sola
  timerAttivi.push(setInterval(() => { if (dati.prodotti.some((p) => p.stato_modello === "in_creazione")) aggiorna(); }, 4000));

  modulo.onsubmit = async (e) => {
    e.preventDefault();
    $("#cat-errore").hidden = true;
    const corpo = new FormData(modulo);
    ["foto", "modello"].forEach((k) => { if (!modulo.elements[k].files.length) corpo.delete(k); });
    if (corpo.get("tipo") === "prodotto" && corpo.get("categoria") === "Illuminazione") {
      // lampada tonda: profondità = diametro; altezza tipica del tipo di luce
      if (!+corpo.get("profondita")) corpo.set("profondita", corpo.get("larghezza"));
      if (!+corpo.get("altezza")) corpo.set("altezza", { faretto: 2, plafoniera: 6, sospensione: 25, applique: 20 }[corpo.get("tipo_luce")] || 6);
    }
    try {
      const p = await api("/api/catalogo", { method: "POST", body: corpo });
      const tipoAttuale = modulo.elements.tipo.value;
      modulo.reset();
      tipoModulo(tipoAttuale);
      $("#cat-nome-foto").textContent = "JPG o PNG, su sfondo il più possibile neutro";
      $("#cat-nome-modello").textContent = "GLB, GLTF, OBJ o FBX del produttore";
      mostraMessaggio(p.foto && p.stato_modello !== "pronto"
        ? `${p.nome} salvato. Se vuoi, crea il modello 3D dalla foto con ✨.` : `${p.nome} salvato nel catalogo.`, "ok");
      aggiorna();
    } catch (err) { $("#cat-errore").textContent = err.message; $("#cat-errore").hidden = false; }
  };
  disegna();
}

// ------------------------------------------------------------ MAPPA (RADAR)

async function paginaMappa(id) {
  mostra("#t-mappa");
  const [m, d] = await Promise.all([api(`/api/progetti/${id}/mappa`), api(`/api/progetti/${id}`)]);
  if (d.stato?.stato !== "mappa_pronta") { location.hash = d.stato?.stato === "finito" ? `#/progetto/${id}` : `#/lavoro/${id}`; return; }
  if (m.tipo_ambiente && m.tipo_ambiente.length <= 60) $("#m-titolo").textContent = `Ecco cosa ho capito: ${m.tipo_ambiente.toLowerCase()}`;
  $("#m-descrizione").textContent = m.descrizione || "";
  $("#m-costo").textContent = euro(d.costo_euro);
  let elementi = m.elementi;
  let vista = null;

  const caricaViewer = () => {
    const pos = vista && vista.isLoaded() ? { yaw: vista.getYaw(), pitch: vista.getPitch(), hfov: vista.getHfov() } : {};
    if (vista) { try { vista.destroy(); } catch (e) { /* già chiuso */ } viewerAttivi = viewerAttivi.filter((v) => v !== vista); }
    vista = viewer("v-mappa", `/api/progetti/${id}/file/mappa.jpg?v=${Date.now()}`, pos);
  };

  const disegnaElenco = () => {
    const nomi = { fisso: "Fisso", rinnova: "Rinnova", togli: "Togli" };
    $("#m-elenco").innerHTML = elementi.map((e, i) => `
      <li>
        <span class="num ${e.categoria}">${i + 1}</span>
        <span>${e.nome}${e.categoria === "fisso" && e.blocca_pixel ? " 🔒" : ""}<small>${e.presenze.length} vist${e.presenze.length === 1 ? "a" : "e"}</small></span>
        <select data-id="${e.id}">
          ${["fisso", "rinnova", "togli"].map((c) => `<option value="${c}" ${c === e.categoria ? "selected" : ""}>${nomi[c]}</option>`).join("")}
        </select>
      </li>`).join("");
    document.querySelectorAll("#m-elenco select").forEach((sel) => sel.addEventListener("change", async () => {
      sel.disabled = true;
      const categorie = Object.fromEntries(elementi.map((e) => [e.id, e.categoria]));
      categorie[sel.dataset.id] = sel.value;
      const r = await api(`/api/progetti/${id}/mappa`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ categorie }) });
      elementi = r.elementi;
      disegnaElenco();
      caricaViewer();
    }));
  };

  disegnaElenco();
  caricaViewer();
  $("#m-conferma").onclick = async () => {
    $("#m-conferma").disabled = true; $("#m-conferma").textContent = "Avvio…";
    const categorie = Object.fromEntries(elementi.map((e) => [e.id, e.categoria]));
    await api(`/api/progetti/${id}/conferma`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ categorie }) });
    location.hash = `#/lavoro/${id}`;
  };
}

// ------------------------------------------------------------ CONSEGNA

async function paginaConsegna(id) {
  mostra("#t-consegna");
  const d = await api(`/api/progetti/${id}`);
  if (d.stato?.stato === "in_corso") { location.hash = `#/lavoro/${id}`; return; }
  const file = (n) => `/api/progetti/${id}/file/${n}`;

  $("#c-data").textContent = d.data;
  $("#c-richiesta").textContent = `“${d.richiesta}”`;
  const tipo = d.analisi?.tipo_ambiente || "";
  const titoli = { rinnova: "Il tuo 360 ristrutturato", prodotto: "Prova prodotto nella stanza", riprogetta: "La stanza riprogettata",
    arreda: "La stanza arredata" };
  $("#c-titolo").textContent = tipo && tipo.length <= 60 ? tipo : (titoli[d.servizio] || titoli.rinnova);
  let suf = "", varianteAttiva = null;
  $("#c-scarica").href = file("risultato_360.jpg") + "?scarica=1";
  $("#c-scarica-pd").href = file("prima_dopo.jpg") + "?scarica=1";
  $("#c-cartella").onclick = () => api(`/api/progetti/${id}/apri-cartella`, { method: "POST" });
  $("#c-rifai").onclick = async () => {
    if (!(await chiediConferma("Rifare lo stesso lavoro?", "Si riparte dal rilievo con la stessa foto.", "Rifai"))) return;
    const r = await api(`/api/progetti/${id}/rifai`, { method: "POST" });
    location.hash = `#/lavoro/${r.id}`;
  };

  // qualità
  const c = d.controllo;
  const ultima = (d.versioni || []).slice(-1)[0];
  if (ultima) {
    const f = Math.round(ultima.fedelta_geometrica);
    $("#c-voto").textContent = f;
    $("#c-anello-valore").style.strokeDasharray = `${f} 100`;
    $("#c-anello-valore").style.stroke = f >= 85 ? "var(--verde)" : f >= 70 ? "var(--giallo)" : "var(--rosso)";
    $("#c-voto-testo").textContent = f >= 85 ? "Geometria fedele" : f >= 70 ? "Da controllare" : "Geometria alterata";
    $("#c-struttura").textContent = `${f}% dei bordi di porte, finestre e angoli coincide · versione ${ultima.versione}`;
    const rimessi = (ultima.fissi || []).filter((x) => x.rimesso_originale).map((x) => x.nome);
    $("#c-giudizio").textContent = (ultima.correzione ? `Correzione applicata: “${ultima.correzione}”. ` : "") +
      (rimessi.length ? `Pixel originali rimessi su: ${rimessi.join(", ")}. ` : "") +
      "Guarda anche la vista “Bordi”: rosso = bordo della foto vera, verde = coincide col risultato.";
    $("#c-correzioni-box").hidden = false;
    const nomi = { dimensioni: "Stanza cambiata", aperture: "Porta/finestra spostata", griglia: "Griglia o etichette copiate",
      misure_mobili: "Mobile troppo grande", oggetti: "Oggetti non richiesti", pavimento: "Pavimento non cambiato", bordi: "Bordi 0°/360°" };
    const invia = async (corpo) => {
      if (!(await chiediConferma("Mando la correzione a ChatGPT?", "Costo circa 0,10 €.", "Invia"))) return;
      await api(`/api/progetti/${id}/correggi`, { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...corpo, variante: varianteAttiva }) });
      location.hash = `#/lavoro/${id}`;
    };
    $("#c-correzioni").innerHTML = Object.keys(CORREZIONI).map((k) => `<button data-k="${k}" title="${CORREZIONI[k]}">${nomi[k] || k}</button>`).join("");
    document.querySelectorAll("#c-correzioni [data-k]").forEach((b) => b.onclick = () => invia({ chiave: b.dataset.k }));
    $("#c-invia-correzione").onclick = () => { const t = $("#c-testo-correzione").value.trim(); if (t) invia({ testo: t }); };
  } else if (c) {
    $("#c-voto").textContent = c.voto;
    $("#c-anello-valore").style.strokeDasharray = `${c.voto * 10} 100`;
    $("#c-anello-valore").style.stroke = c.voto >= 8 ? "var(--verde)" : c.voto >= 6 ? "var(--giallo)" : "var(--rosso)";
    $("#c-voto-testo").textContent = c.voto >= 8 ? "Consegnabile" : c.voto >= 6 ? "Da rivedere" : "Non consegnabile";
    $("#c-struttura").textContent = c.punteggio_struttura != null ? `${Math.round(c.punteggio_struttura)}/100` : "—";
    $("#c-giudizio").textContent = c.giudizio;
    const colore = { alta: "pill-rossa", media: "pill-gialla", bassa: "" };
    $("#c-problemi").innerHTML = (c.problemi || []).map((p) =>
      `<li><span class="pill ${colore[p.gravita] || ""}">${p.gravita}</span><span><strong>${p.dove}:</strong> ${p.descrizione}</span></li>`).join("");
  } else {
    $("#c-giudizio").textContent = "Controllo qualità non disponibile per questo progetto.";
  }
  $("#c-costo").textContent = euro(d.costo_euro);
  $("#c-costo-dett").textContent = `OpenAI ${euro(d.costo_openai)} · Claude ${euro(d.costo_claude)} · ${d.chiamate} chiamate`;
  const r = d.riepilogo || {};
  $("#c-tempo").textContent = r.minuti_totali ? `${String(r.minuti_totali).replace(".", ",")} min` : "—";
  $("#c-tentativi").textContent = r.tentativi ? `${r.tentativi} tentativ${r.tentativi === 1 ? "o" : "i"}` : "";
  $("#c-modalita").textContent = { rinnova: "Ristruttura", prodotto: "Prova prodotto", riprogetta: "Progetta",
    arreda: "Progetta" }[d.servizio] || "Ristruttura";
  $("#c-file").textContent = d.nome_file || "";

  // viewer prima/dopo sincronizzati
  const conf = $("#confronto");
  let vDopo = viewer("v-dopo", file("viewer_dopo.jpg") + `?v=${Date.now()}`);
  vDopo._immagine = "viewer_dopo.jpg";
  const vPrima = viewer("v-prima", file("viewer_prima.jpg"));
  let guida = vDopo;
  conf.addEventListener("pointerdown", (e) => {
    if (e.target.closest(".maniglia")) return;
    const sopra = $("#v-prima").getBoundingClientRect();
    const xRel = (e.clientX - sopra.left) / sopra.width;
    guida = conf.classList.contains("solo-prima") || (!conf.classList.contains("solo-dopo") && xRel < posizione) ? vPrima : vDopo;
  }, true);
  const sincronizza = () => {
    const altro = guida === vPrima ? vDopo : vPrima;
    try {
      if (guida.isLoaded() && altro.isLoaded()) {
        altro.setYaw(guida.getYaw(), false); altro.setPitch(guida.getPitch(), false); altro.setHfov(guida.getHfov(), false);
      }
    } catch (e) { /* viewer in caricamento */ }
    if (document.body.contains(conf)) requestAnimationFrame(sincronizza);
  };
  requestAnimationFrame(sincronizza);

  // varianti A/B/C (Riprogetta): si cambia variante restando nello stesso punto del 360
  const pronte = d.varianti_pronte || [];
  if (pronte.length) {
    const barra = $("#c-varianti");
    barra.hidden = false;
    const scegli = (k) => {
      varianteAttiva = k; suf = `_${k}`;
      barra.querySelectorAll("button").forEach((x) => x.classList.toggle("attivo", x.dataset.v === k));
      $("#c-scarica").href = file(`risultato_360${suf}.jpg`) + "?scarica=1";
      $("#c-scarica-pd").href = file(`prima_dopo${suf}.jpg`) + "?scarica=1";
      const vista = conf.classList.contains("solo-bordi") ? `controllo_bordi${suf}.jpg` : `viewer_dopo${suf}.jpg`;
      const pos = vDopo.isLoaded() ? { yaw: vDopo.getYaw(), pitch: vDopo.getPitch(), hfov: vDopo.getHfov() } : {};
      try { vDopo.destroy(); } catch (e) { /* già chiuso */ }
      viewerAttivi = viewerAttivi.filter((v) => v !== vDopo);
      vDopo = viewer("v-dopo", file(vista) + `?v=${Date.now()}`, pos);
      vDopo._immagine = vista;
      guida = vDopo;
    };
    barra.innerHTML = pronte.map((k) => `<button data-v="${k}">Variante ${k}</button>`).join("");
    barra.querySelectorAll("button").forEach((b) => b.onclick = () => scegli(b.dataset.v));
    scegli(pronte[pronte.length - 1]);
  }

  // maniglia del confronto
  let posizione = 0.5;
  const maniglia = $("#maniglia"), sopra = $("#v-prima");
  const muovi = (x) => {
    const box = conf.getBoundingClientRect();
    posizione = Math.min(0.98, Math.max(0.02, (x - box.left) / box.width));
    maniglia.style.left = `${posizione * 100}%`;
    sopra.style.clipPath = `inset(0 ${100 - posizione * 100}% 0 0)`;
  };
  maniglia.addEventListener("pointerdown", (e) => {
    maniglia.setPointerCapture(e.pointerId);
    const mv = (ev) => muovi(ev.clientX);
    const su = () => { maniglia.removeEventListener("pointermove", mv); maniglia.removeEventListener("pointerup", su); };
    maniglia.addEventListener("pointermove", mv); maniglia.addEventListener("pointerup", su);
  });

  document.querySelectorAll(".interruttore [data-vista]").forEach((b) => b.addEventListener("click", () => {
    document.querySelectorAll(".interruttore [data-vista]").forEach((x) => x.classList.remove("attivo"));
    b.classList.add("attivo");
    conf.classList.remove("solo-prima", "solo-dopo", "solo-bordi");
    const immagineDopo = b.dataset.vista === "bordi" ? `controllo_bordi${suf}.jpg` : `viewer_dopo${suf}.jpg`;
    if (vDopo._immagine !== immagineDopo) {
      const pos = vDopo.isLoaded() ? { yaw: vDopo.getYaw(), pitch: vDopo.getPitch(), hfov: vDopo.getHfov() } : {};
      try { vDopo.destroy(); } catch (e) { /* già chiuso */ }
      viewerAttivi = viewerAttivi.filter((v) => v !== vDopo);
      vDopo = viewer("v-dopo", file(immagineDopo) + `?v=${Date.now()}`, pos);
      vDopo._immagine = immagineDopo;
    }
    if (b.dataset.vista === "bordi") { conf.classList.add("solo-bordi"); sopra.style.clipPath = ""; guida = vDopo; }
    else if (b.dataset.vista === "prima") { conf.classList.add("solo-prima"); sopra.style.clipPath = ""; guida = vPrima; }
    else if (b.dataset.vista === "dopo") { conf.classList.add("solo-dopo"); sopra.style.clipPath = ""; guida = vDopo; }
    else muovi(conf.getBoundingClientRect().left + posizione * conf.getBoundingClientRect().width);
  }));
  $("#schermo-intero").onclick = () => (document.fullscreenElement ? document.exitFullscreen() : conf.requestFullscreen());
  document.addEventListener("fullscreenchange", () => setTimeout(() => viewerAttivi.forEach((v) => v.resize && v.resize()), 100));
}

// ------------------------------------------------------------ PROGETTI

async function paginaProgetti() {
  mostra("#t-progetti");
  const { progetti } = await api("/api/progetti");
  const elenco = $("#elenco");
  if (!progetti.length) {
    elenco.innerHTML = `<div class="vuoto">Nessun progetto ancora. <a href="#/nuovo">Crea il primo</a>.</div>`;
    return;
  }
  elenco.innerHTML = progetti.map((p) => {
    const st = p.stato?.stato;
    let badge = `<span class="pill">in corso</span>`;
    if (st === "sconosciuto") badge = `<span class="pill">interrotto</span>`;
    else if (st === "mappa_pronta") badge = `<span class="pill pill-gialla">da confermare</span>`;
    else if (st === "rilievo") badge = `<span class="pill pill-gialla">rilievo</span>`;
    else if (st === "rilievo_confermato") badge = `<span class="pill pill-verde">rilievo pronto</span>`;
    else if (st === "errore") badge = `<span class="pill pill-rossa">errore</span>`;
    else if (st === "finito") {
      const v = p.controllo?.voto;
      badge = v == null ? `<span class="pill pill-verde">pronto</span>`
        : `<span class="pill ${v >= 8 ? "pill-verde" : v >= 6 ? "pill-gialla" : "pill-rossa"}">voto ${v}/10</span>`;
    }
    const link = st === "finito" ? `#/progetto/${p.id}` : st === "sconosciuto" ? "#/progetti"
      : st === "mappa_pronta" ? `#/mappa/${p.id}`
      : st && st.startsWith("rilievo") ? `#/rilievo/${p.id}` : `#/lavoro/${p.id}`;
    const img = p.file["miniatura.jpg"] ? `style="background-image:url('/api/progetti/${p.id}/file/miniatura.jpg')"`
      : p.file["mappa.jpg"] ? `style="background-image:url('/api/progetti/${p.id}/file/mappa.jpg')"` : "";
    return `<a class="scheda" href="${link}">
      <div class="scheda-img" ${img}>${badge}</div>
      <div class="scheda-corpo">
        <div class="scheda-testo">${p.richiesta.replace(/</g, "&lt;")}</div>
        <div class="scheda-piede"><span>${p.data} · ${p.modalita === "potenziale" ? "Potenziale" : "Rinnova"}</span><span>${euro(p.costo_euro)}</span></div>
      </div></a>`;
  }).join("");
}

// ------------------------------------------------------------ AVVIO E NAVIGAZIONE

let VERSIONE = null;

async function naviga() {
  // se il programma è stato aggiornato mentre la pagina era aperta, si ricarica da sola
  try {
    const v = (await api("/api/versione")).versione;
    if (VERSIONE && v !== VERSIONE) { location.reload(); return; }
    VERSIONE = v;
  } catch (e) { /* server non raggiungibile */ }
  const [, sezione, id] = (location.hash || "#/nuovo").split("/");
  document.querySelectorAll("nav a").forEach((a) => a.classList.toggle("attivo",
    a.dataset.nav === (["progetti", "progetto", "mappa", "rilievo"].includes(sezione) ? "progetti" : sezione === "nuovo" ? "nuovo"
      : sezione === "catalogo" ? "catalogo" : "")));
  try {
    if (sezione === "lavoro" && id) paginaLavoro(id);
    else if (sezione === "progetto" && id) await paginaConsegna(id);
    else if (sezione === "mappa" && id) await paginaMappa(id);
    else if (sezione === "rilievo" && id) await paginaRilievo(id);
    else if (sezione === "progetti") await paginaProgetti();
    else if (sezione === "catalogo") await paginaCatalogo();
    else if (sezione === "casa" && id) await paginaCasa(id);
    else paginaNuovo();
  } catch (e) {
    pagina.innerHTML = `<div class="pannello errore-box">${e.message}</div>`;
  }
  window.scrollTo(0, 0);
}

(async function avvio() {
  try {
    const p = await api("/api/preset");
    FASI = p.fasi; PRESET = p.preset; PRESET_ARREDO = p.preset_arredo || []; CORREZIONI = p.correzioni || {};
    const s = await api("/api/salute");
    // ogni chiave serve solo ad alcune funzioni: si dice quali, senza bloccare il resto
    const mancano = [];
    if (!s.anthropic) mancano.push("Anthropic (serve per leggere le piantine)");
    if (!s.openai) mancano.push("OpenAI (serve solo per i lavori sulle foto 360; il render 3D da piantina funziona lo stesso)");
    if (mancano.length) {
      const avviso = $("#avviso-chiavi");
      avviso.hidden = false;
      avviso.textContent = `Nel file .env manca la chiave ${mancano.join(" e la chiave ")}.`;
    }
  } catch (e) { /* server non raggiungibile: la pagina mostrerà l'errore */ }
  window.addEventListener("hashchange", naviga);
  naviga();
})();
