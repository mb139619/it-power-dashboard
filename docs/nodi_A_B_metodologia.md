# Nodi metodologici A e B — contabilità del residuo e struttura del prezzo (2025)

> **Vocabolario di provenance.** L'etichettatura observed / derived / proxy / assumption usata
> in tutto questo documento, e la pratica di mettere per iscritto ciò che i dati liberi non
> possono sostenere, sono adottate da
> [lptva/gb-power-dashboard](https://github.com/lptva/gb-power-dashboard). È applicando quella
> disciplina al bilancio italiano che JC#6 è stato ritirato invece di essere tarato ancora.


> Sezioni da integrare nella guida. Entrambi i nodi sono stati **verificati empiricamente
> prima di essere formalizzati** (riconciliazione su dati ENTSO-E, zona IT_NORD), non
> assunti da manuale: è la ragione per cui la definizione qui sotto è scritta una volta
> sola e non ha punti interrogativi al centro. Cross-ref principali: §12 (modelli
> fondamentali), §13 (EPF per il trading).

---

## A. Residual load: contabilità dei boundary e definizione operativa

Il residual load è il pilastro del meccanismo di formazione del prezzo (residual demand →
merit order → prezzo, cfr. §13). Prima di definirlo bisogna sciogliere un nodo di
contabilità che è facile sbagliare in modo sottile, ed è il nodo dove un boundary
disallineato genera il classico bug del "residuo negativo a mezzogiorno".

### A.1 L'identità di bilancio

Tutto parte dalla conservazione dell'energia. In ogni istante:

```
Fabbisogno = Produzione netta totale + Import − Export − Assorbimento pompaggi
```

dove `Produzione netta totale` = termico + idro + geo + eolico + FV (netto degli ausiliari
di centrale, convenzione ENTSO-E). L'identità chiude per costruzione. Il problema non è
l'identità: è che **una parte della produzione FV non è misurata ma stimata**, quindi né
il fabbisogno né la produzione totale sono grandezze *osservate* — sono ricostruite.

### A.2 I due boundary e il fatto italiano

Esistono due grandezze che entrambe si possono chiamare "domanda", separate dal
trattamento della generazione distribuita (soprattutto FV su rete di distribuzione):

- **Domanda netta (trasmissione)** — quella che il sistema *vede* in tempo reale: già al
  netto di *tutto* il FV distribuito, sia la quota immessa in rete sia quella
  autoconsumata dietro il contatore. È l'analogo dell'INDO britannico, ma con un buco di
  misura più grande perché in Italia l'autoconsumo distribuito è enorme.
- **Domanda gross (ricostruita)** — il fabbisogno vero, ciò che il paese consuma: pari
  alla domanda netta più la *stima* del FV distribuito. È **Estimated**, non Observed.

Il fatto italiano che fissa tutto, documentato: Terna riceve dai distributori le misure
dell'energia **immessa** dagli impianti di generazione distribuita (aggregata per area
per lo Scambio sul Posto ≤ 55 kW, puntuale per impianto negli altri casi), ma **non riceve
alcun dato sull'energia prodotta**. La differenza tra immessa e prodotta è l'*autoconsumo*
dietro il contatore, che è invisibile: non appare come generazione, appare come domanda in
meno. Di conseguenza Terna *ricostruisce* il FV distribuito con un modello di stima in
near-real-time (tecniche probabilistiche + machine learning). Ogni grandezza che dipende
da questa stima eredita il badge **Estimated**.

### A.3 La trappola del doppio conteggio

Il residuo si vuole definire come la parte di domanda servita dalla generazione
dispacciabile:

```
Residual = Domanda − Rinnovabili must-run (eolico + solare + idro fluente + geo)
```

Il bug scatta se si **mescolano boundary diversi**, in due direzioni:

1. Domanda **netta** (già priva del distribuito) − serie solare **completa** (che include
   il distribuito) → il FV distribuito è sottratto **due volte** → a mezzogiorno assolato
   il residuo va sotto zero.
2. Domanda **gross** − serie solare che cattura solo l'utility-scale → si sottrae troppo
   poco → residuo gonfiato.

La regola che previene entrambi è una sola: **domanda e generazione dalla stessa
ricostruzione, allo stesso boundary.**

### A.4 Risultato verificato: l'errore di chiusura È la generazione distribuita

Riconciliando su ENTSO-E si trova che il **carico è sul boundary net, il solare è sul
boundary gross** (include il distribuito). L'errore di chiusura del bilancio,

```
eps = Load − (Σ generazione − pompaggio + import netto)
```

risulta **negativo e a forma di campana solare** (zero di notte, minimo a mezzogiorno).
Facendo l'algebra sull'identità, se il carico è net e il solare è gross:

```
eps = −(generazione distribuita)
```

Quindi **−eps di giorno è una stima al prim'ordine del FV distribuito, ricavata dal solo
ENTSO-E** (senza chiave Terna). Sulla zona IT_NORD, giugno, il picco di mezzogiorno è
dell'ordine dei ~3,5 GW. Termini residui minori (perdite di rete, eolico distribuito,
averaging) rendono la stima di prim'ordine, non esatta: va validata per ordine di
grandezza contro la produzione FV distribuita **mensile** pubblicata da Terna nel Rapporto
Mensile (numero pubblico, non un'API).

### A.5 Invarianza del residuo e definizione operativa

Risultato che scioglie la domanda "gross o net": **il residuo è invariante rispetto al
boundary, purché si sia coerenti.** Il FV distribuito si cancella — abbassa la domanda *e*
aggiunge must-run della stessa quantità. La scelta non è "gross vs net", è "coerenza".

Definizione operativa (boundary market-facing, coerente), con lo **split idro** corretto:

```
D_pv  = max(−eps, 0)                          # FV distribuito stimato
R     = Load − (Solar_gross − D_pv) − Wind − Idro_fluente − Geo
```

Verificato algebricamente identico al residuo gross e a `(generazione dispacciabile −
pompaggio + import netto)`.

**Split idro (punto che la GB non ha):** l'idro non è un blocco unico.
- Sottrai come must-run **solo il fluente (run-of-river)**.
- Serbatoio e pompaggio (generazione) sono **dispacciabili** → restano *nel* residuo.
- Il pompaggio in assorbimento è **domanda**, non generazione negativa.

Sommare tutto l'idro nel must-run sbaglia il segno del residuo nelle ore di peak-shaving.

### A.6 Provenance e trasferimento alle feature di forecast

- **Residual load → Estimated** (eredita la stima −eps del distribuito).
- **Serie FV distribuito → Estimated** (metodo dell'errore di chiusura; cross-check vs
  Terna mensile).

Nota critica per il §13: la disciplina di boundary conta **soprattutto nelle feature di
forecast**. Il residuo che alimenta il modello EPF non è quello ricostruito ex-post — è
`previsione_domanda − previsione_eolico − previsione_solare`, a gate closure. Se la
previsione di carico e le previsioni di rinnovabili vengono da fonti su boundary diversi,
si reintroduce il doppio conteggio *dentro la feature su cui il modello si allena* — bias
sistematico, peggiore di un artefatto negli actuals. Fonte-carico e fonte-rinnovabili
devono condividere un boundary.

---

## B. Il prezzo oggi: due rotture strutturali nel 2025 e l'asse temporale

Post-2025 la domanda "cos'è il prezzo" non ha una risposta scalare, e la serie prezzi
contiene **due rotture strutturali in date diverse** — distinzione essenziale per l'asse
temporale del dashboard.

### B.1 Due riforme, due date

- **1° gennaio 2025 — riferimento e sbilanciamenti.** Il PUN diventa **PUN Index GME**,
  calcolato come media dei prezzi **zonali** pesata per i volumi acquistati in ciascuna
  zona. I consumatori pagano lo zonale; il PUN Index GME resta indice di riferimento (PPA,
  indicizzazioni retail), con un meccanismo transitorio di **perequazione** che compensa
  la differenza. Sul bilanciamento parte la riforma **TIDE** con sbilanciamenti a 15
  minuti. **Il MGP resta orario.**
- **1° ottobre 2025 — mercato del giorno prima.** Il MGP passa a **MTU 15 minuti** via il
  go-live SDAC (trading day 30 settembre 2025, consegna 1° ottobre; originariamente
  previsto 11 giugno 2025, poi rinviato). 96 quarti d'ora al giorno; prezzo di clearing su
  base 15 minuti; offerte orarie ancora possibili (Euphemia accoppia le risoluzioni
  15/30/60 senza arbitraggio tra loro); un indice a 60 minuti è pubblicato come media
  aritmetica dei prezzi quartorari.

### B.2 Le due rotture nella serie prezzi

A gennaio cambia **cosa** è il prezzo di riferimento (nazionale → zonale); a ottobre cambia
la **granularità** del MGP (orario → quartorario). Entrambe sono il tipo di break che fa
fallire un validation guard sull'asse temporale.

### B.3 Conseguenza sull'asse temporale e scelta della finestra

**Decisione di design:** la serie del dashboard parte da **1° ottobre 2025**. In questo
modo si vive interamente in regime unico **15-minuti-zonale** e si evitano *entrambe* le
rotture. L'ETL vede una sola risoluzione, il guard sull'asse non deve tollerare eccezioni,
le DST edge case si gestiscono su un'unica griglia quartoraria.

Comunicazione (due cose distinte, due posti distinti):
- **Cutoff dati** (`data window: 2025-10-01 → present`): fatto di copertura, esplicito e
  vicino al dato (header / meta). Un desk lo legge come rigore.
- **Rationale** (perché ottobre 2025): contenuto da metodologia — dimostra consapevolezza
  delle due riforme, non è una scusa per la finestra corta.

### B.4 Cosa è "il prezzo": una gerarchia, non un numero

- **Prezzi zonali** (7 zone) — il primitivo **Observed**; è ciò che i generatori incassano
  e che fissa il marginale del merit order. Base layer del pannello prezzo.
- **PUN Index GME** — aggregato **derivato** (media pesata degli zonali). Calcolato
  esattamente da zonali e volumi pubblici → **Observed/derived**, non Estimated. Numero
  headline nazionale, da etichettare come "media derivata", non come prezzo di clearing.
- **Prezzo al consumatore** = zonale + perequazione — prospettiva retail, deprioritizzata
  per un dashboard trading.

### B.5 I 15 minuti e il sawtooth (opportunità di pannello)

La granularità 15 minuti genera un *sawtooth* intra-orario: i produttori solari, costretti
a offrire medie orarie mentre la generazione segue pattern quartorari, restano esposti a un
mismatch non chiudibile sul day-ahead. Un pannello che mostra il sawtooth ai confini d'ora
attorno alle rampe solari dimostra padronanza della **microstruttura post-ottobre 2025**,
non del mercato da manuale — differenziatore reale per un profilo con background finance.

---

## Voci per il glossario

- **Boundary (net / gross)** — livello a cui una grandezza di domanda è misurata: net =
  al netto della generazione distribuita (trasmissione); gross = domanda vera ricostruita.
- **Immessa vs prodotta (GD)** — energia distribuita iniettata in rete (parzialmente
  misurata) vs energia totale prodotta (non riportata a Terna); la differenza è
  l'autoconsumo, invisibile.
- **eps (errore di chiusura)** — scarto dell'identità di bilancio; con carico net e solare
  gross, ≈ −(generazione distribuita).
- **PUN Index GME** — dal 2025, media dei prezzi zonali pesata per i volumi acquistati per
  zona; indice di riferimento (non prezzo di clearing).
- **MTU** — Market Time Unit; sul MGP italiano orario fino al 30/9/2025, quartorario dal
  1/10/2025.
- **Perequazione** — meccanismo transitorio che compensa la differenza tra prezzo zonale e
  PUN Index GME per il consumatore.

## Registro judgement calls (stile dashboard GB)

1. **Finestra dati dal 1° ottobre 2025.** Scelta per restare in regime 15-min post-SDAC ed
   evitare la rottura di granularità del MGP; il cambio PUN → PUN Index GME (1/1/2025) è a
   monte della finestra e quindi non impatta. Trade-off: si rinuncia allo storico
   pre-riforma in cambio di un asse temporale omogeneo.
2. **Residual load stampato Estimated.** Dipende dalla stima −eps del FV distribuito, che
   Terna ricostruisce e non misura; non è spacciato per Observed.
3. **FV distribuito da errore di chiusura (−eps).** Stima di prim'ordine ENTSO-E-only;
   validata per ordine di grandezza contro il dato mensile Terna, non contro una misura
   puntuale (che non esiste come dato pubblico).
4. **Split idro nel must-run.** Solo il fluente è sottratto; serbatoio e pompaggio restano
   dispacciabili nel residuo. Assunzione: la classificazione ENTSO-E per PSR type (B11 vs
   B12/B10) è affidabile per la zona/finestra usata.
5. **Stima del FV distribuito a scala oraria (non quartoraria).** Il residuo grezzo a 15
   min (`Load − solare − eolico − fluente − geo`) è liscio e valido. L'artefatto (dente di
   sega) entra *solo* attraverso la correzione del distribuito `D_pv = −eps`, perché eps
   dipende dalla chiusura del bilancio completo, che include il **net_import**. Misurato:
   su IT_NORD il net_import ha una volatilità sub-oraria *reale* (~1,9 GW di swing
   intra-orario, vs ~250 MW delle altre componenti) — ramping degli interconnector e aste
   intraday quartorarie — non correlata con carico/solare, quindi non si cancella nel
   bilancio e domina eps a 15 min. Non è una scalinata oraria (i timestamp e i valori sono
   davvero quartorari): è rumore fisico. **Fix:** stimare `D_pv` da eps **orario** (media
   d'intervallo), dove il rumore si media via e resta la campana solare pulita, poi
   riportarlo a 15 min per interpolazione — legittimo perché il FV distribuito è
   genuinamente lento. Il net_import, che ha struttura reale a 15 min, non va **mai**
   interpolato/mediato per il pannello prezzo. Ogni serie alla sua granularità naturale.
6. **Offset non-solare nel bilancio (perdite di rete).** eps non è FV distribuito puro: di
   notte, quando il distribuito è zero per definizione, eps su IT_NORD vale ~−760 MW invece
   di ~0 (misurato, ottobre 2025). È un offset ~costante — verosimilmente perdite di rete
   (il carico ENTSO-E le include, la generazione è netta) più eventuale generazione
   distribuita non-solare notturna. Lasciato dentro, gonfia −eps: la quota distribuita
   risultava ~80% del solare totale su NORD (implausibile). **Fix:** sottrarre la baseline
   notturna di eps (per-giorno) prima di clippare, isolando la sola componente che varia col
   sole. La baseline è *misurata* dai dati notturni, non scelta. Assunzione di secondo
   ordine: l'offset è ~costante nelle 24h; le perdite in realtà scalano un po' col carico —
   trascurabile rispetto ai ~760 MW rimossi, raffinabile modellando l'offset come frazione
   del carico. Nota di scala: la quota distribuita è **zonale**, non nazionale — NORD è
   distributed-heavy (tetti, pochi impianti utility), il Sud è utility-heavy; una banda di
   plausibilità unica per tutte le zone dà falsi allarmi.
7. **Quota distribuita affidabile solo dove il solare è sostanziale.** La scomposizione
   distribuito/utility via −eps degrada dove il solare della zona-finestra è scarso: il
   rapporto distribuito/totale è dominato dal rumore residuo (perdite mal mediate, flussi
   cross-border zonali, imprecisioni del bilancio) su un denominatore minuscolo, fino a
   superare il 100% — impossibile per definizione. Evidenza su due mesi e sette zone: CALA
   passa da 146% (ott-2025) a 322% (giu-2026), la zona a solare più basso col numero più
   impossibile; CNOR passa da 111% (ott, inaffidabile) a 70% (giu, plausibile) perché col
   sole estivo ha abbastanza solare da diluire il rumore. Il limite **non è per-zona fisso**
   ma dipende da quanto solare c'è nella zona-finestra. Il pattern geografico sulle zone a
   solare abbondante resta valido e coerente (NORD/CSUD alti; SUD ~7%, SICI ~2% bassi, come
   atteso per le zone utility-heavy). NON invalida il nodo A: definizione di residuo e fix
   del boundary sono corretti ovunque — degrada solo la *scomposizione*. `zone_scan.py`
   auto-marca `UNRELIABLE:>100%` e `noisy-baseline` dai dati, così lo strumento non mostra
   numeri impossibili senza avvertimento.

---


---

## JC#6 — RITIRATO (15-lug-2026): il PV distribuito non è identificabile

**Stato: JC#6 è ritirato in entrambe le sue versioni.** Non stimiamo più il PV distribuito. Il
residuo si legge dal **lato offerta**, con soli dati osservati. Questa sezione conserva il
percorso, perché il *perché* del fallimento è la parte che vale.

### Le due versioni tentate, e come sono cadute

**v1 — baseline notturna.** `D_pv(t) = max(0, -(eps(t) - baseline_notte))`, assumendo l'offset
non-solare costante nelle 24h. **Smentita dai dati** (IT_NORD 14-lug-2026): con sole a zero,
eps va da +718 (03:00) a +3.205 MW (20:00). L'offset non è costante. Effetto sul dato
pubblicato: 584 MW di "fotovoltaico" **alle 03:00**, e il rapporto D_pv/Solare che *decresceva*
al salire del sole (33,8% alle 07:00 → 9,6% alle 09:00). Rumore, non segnale.

**v2 — quota strutturale con effetti fissi.** `eps_t = delta_ora + delta_mese - k*Solar_t`, con
`D_pv = k*Solar`. Idea: k è una proprietà del parco installato, e le dummy orarie assorbono
l'offset senza doverne assumere la causa. k identificato dalla variazione within-hour /
across-day del solare. **Smentita dal fit su tutte e sette le zone** (finestra piena, ~6.800
ore per zona):

| zona | k | R² | verdetto |
|------|-------|------|----------|
| NORD | 47,9% | 0,47 | dentro [0,1] ma **contraddice** il controllo campana (~33%) |
| CNOR | **−124,4%** | 0,57 | impossibile |
| CSUD | −53,3% | 0,47 | impossibile |
| SUD | −57,9% | 0,34 | impossibile |
| CALA | **+332,8%** | 0,53 | impossibile |
| SICI | −65,5% | 0,52 | impossibile |
| SARD | −27,5% | 0,49 | impossibile |

**Sei zone su sette danno quote fisicamente impossibili, con R² tra 0,34 e 0,57 — tutti
simili.** È il punto decisivo: se la qualità del fit non distingue il caso buono da quello
impossibile, non è rumore, è **misspecificazione**. CALA lo sigilla: R² 0,53 con k = +333%.
E NORD, l'unico entro i limiti, dà 47,9% contro il ~33% che il controllo indipendente
(profondità della campana / solare) misura in due stagioni opposte (0,36 a luglio, 0,31 a
ottobre): dentro i limiti non vuol dire giusto.

**Diagnosi.** Qualcosa co-varia col solare *entro la stessa ora, tra giorni diversi* — cioè
proprio la variazione da cui k dovrebbe identificarsi. Il candidato naturale sono i **flussi**:
nei giorni di sole la zona esporta di più / importa di meno, e quel movimento entra in eps
insieme al solare; la regressione lo attribuisce al solare. Nelle zone piccole attraversate da
flussi grandi rispetto alla loro taglia (CNOR, CALA) il termine di flusso domina e ribalta il
segno. Con i soli dati liberi non abbiamo uno strumento che separi le due cose.

**Conclusione: l'errore di chiusura non identifica il PV distribuito.** Non è questione di
taratura o di finestra: è strutturale.

### Cosa facciamo adesso — residuo dal lato offerta

    R = dispacciabile - pompaggio + net_import

Stessa grandezza economica (quanto deve coprire il merit order), vista da chi la copre invece
che da chi la consuma. L'identità di bilancio rende le due definizioni uguali quando il
bilancio chiude — ed è quello che il test `test_supply_side_residual_equals_demand_side_when_the_balance_closes`
verifica. Ma questa forma usa **solo colonne osservate**: niente k, niente D_pv.

Analogamente `renewable_share = must-run / offerta totale`: numeratore e denominatore sullo
stesso confine (lordo), niente mescolanza di Load netto con Solar lordo — l'errore che il nodo
A esiste per prevenire. Bonus: il KPI ora significa la stessa cosa della didascalia del
pannello generation mix ("renewables X% of supply"), che prima divergeva.

**Guadagni**, tutti diretti:
- **Zero stime**: badge `Derived`, non `Estimated`.
- **Tutte e sette le zone allo stesso modo**: sparisce il ⚠ su 6 zone, il selettore zonale
  torna pienamente utile.
- **Niente ereditarietà**: prima residuo *e* quota rinnovabile poggiavano entrambi su un k che
  ora sappiamo inaffidabile.

**Costo, dichiarato.** Le due definizioni differiscono esattamente di `eps`, che non sparisce.
**Misurato su IT_NORD, finestra 2025-10-01 → 2026-07-16 (27.649 step): |eps| medio = 2.723 MW,
p95 = 6.522 MW** — ordine del 10-15% del carico di zona. Con R dal lato offerta quel
disaccordo resta, ma smette di essere *silenziosamente attribuito al fotovoltaico* e diventa un
gap esplicito: pubblichiamo `eps` come colonna (`closure_error`, Derived) e la sua magnitudine
in `meta.balance_gap`. Meglio un numero osservato con una discrepanza dichiarata che uno
stimato che sappiamo sbagliato.

**Cosa c'è dentro eps — e cosa NON c'è.** Le ore notturne lo dimostrano: con solare a zero, eps
vale +700..+3.200 MW (IT_NORD, 14-lug-2026). **Alle 03:00 non è il sole.** Il contenuto
plausibile è generazione distribuita **non riportata** (cogenerazione industriale, piccolo
idro, biogas: ENTSO-E richiede il reporting sopra soglie di capacità, sotto è invisibile), più
perdite di rete e disallineamenti nel reporting dei flussi. La formulazione originale del nodo
A — `eps ≈ -(distributed generation)` — era corretta; l'errore delle v1/v2 è stato leggere
*generation* come *solar*, attribuendo l'intero buco al fotovoltaico. Da qui i 584 MW di "PV"
alle 03:00: non un baco di implementazione, ma l'attribuzione stessa.

### Validazione esterna di eps (16-lug-2026, API Terna)

Terna pubblica una categoria **Self-consumption** che ENTSO-E non ha. Confrontata con eps
(profilo orario nazionale, 14-lug-2026, in MW):

| | Self-consumption Terna (nazionale) | eps IT_NORD |
|---|---|---|
| notte (00-03) | 2.616 | +1.007 |
| mezzogiorno (11-14) | 9.578 | -1.361 |
| campana (giorno - notte) | 6.962 | 2.368 |

**Due conclusioni.**

1. **Lo zoccolo notturno esiste ed è grande.** Con il sole a zero l'Italia autoconsuma 2,6 GW:
   non è fotovoltaico ma cogenerazione industriale, biogas, piccolo idro — generazione
   distribuita sotto le soglie di reporting ENTSO-E. È esattamente il contenuto ipotizzato per
   eps sopra, ora **misurato**. La quota attribuibile a IT_NORD (~1,0-1,3 GW su base carico)
   combacia con l'eps notturno osservato (+1.007 MW). Ne segue che attribuire l'intero eps al
   fotovoltaico — quello che facevano JC#6 v1 e v2 — è sbagliato **per costruzione**, non per
   taratura: circa metà del buco non ha nulla a che vedere col sole.
2. **La quota distribuita reale è ~28%.** Bump solare dell'autoconsumo (6.962) sul solare
   totale (Photovoltaic 18.085 + bump): **27,8%**. Confronto coi nostri stimatori:
   controllo campana 31-36% (vicino), regressione JC#6-v2 **47,9%** (sovrastima di ~20 punti).
   La regressione era quindi distorta anche su IT_NORD, l'unica zona che superava il vincolo
   [0,1] — il verdetto "ok" certificava solo la plausibilità del segno, non la correttezza.

**Perché questo non ripristina la stima.** Il dato Terna è **solo nazionale**: non esiste per
zona di mercato, quindi non può alimentare un residuo zonale. Serve a spiegare eps, non a
eliminarlo. Il residuo resta letto dal lato offerta.

**Limite che ne consegue, dichiarato.** Con un buco di ~2,7 GW medi, qualunque analisi *lato
domanda* su dati liberi è fragile in questo mercato. Il residuo lato offerta non ne risente
(non usa eps), ma il limite va conosciuto e non aggirato con una stima.

### Cosa resta vero del nodo A

La distinzione di boundary — ENTSO-E dà **Load netto** e **Solar lordo** — è corretta e
importante: è la ragione per cui la forma domanda-side richiede D_pv per essere coerente. Il
nodo A non è invalidato: ci ha detto *perché* la strada domanda-side è impraticabile con dati
liberi, ed è ciò che motiva la forma supply-side.

### Codice

`etl/transform.py`: `residual_load_supply()`, `renewable_share()`, `total_supply()`,
`closure_error()` (ora solo diagnostica). Ritirati: `estimate_dpv_share`, `distributed_pv`,
`residual_load` (demand-side), `renewable_penetration`, e `zone_scan.py` (esisteva solo per
validare k).

---

## Known gaps (deliberate scope decisions)

### PV distribuito — gap dichiarato (JC#6 ritirato)

Il fotovoltaico dietro il contatore esiste ed è grande (ordine dei GW su NORD), ma **non è
osservabile con dati liberi** e non è identificabile dall'errore di chiusura (sopra) — che
peraltro non contiene solo lui: |eps| medio 2,7 GW su IT_NORD, di cui una parte sostanziale
presente anche di notte, quando il sole non c'è. Terna
pubblica una cifra mensile sul distribuito: utile per un ordine di grandezza, non per una serie
oraria per zona. Non lo stimiamo e non lo pubblichiamo. Il suo effetto resta dentro `eps`, che
pubblichiamo come `closure_error` con la sua magnitudine in `meta.balance_gap`: un buco
dichiarato invece di un numero inventato.


### PSV–TTF basis — deferred (no clean free source)
The Italian gas leg would ideally include the **PSV–TTF basis** (the premium of Italian gas
over the European TTF benchmark), the gas twin of the zonal power spreads. It is deliberately
**not** implemented, for reasons worth stating:

- **The true PSV is a commercial datum.** The reference PSV index (PSVDA_MM, used by ARERA)
  is assessed by **ICIS Heren** on OTC transactions at Snam's Virtual Trading Point — paid.
  What GME publishes for free (**MGP-GAS**) is a *related but different* price (a subset of
  exchange trades), not the PSV. GME's newer **IGI** index is free and public but exposed only
  via the website, not an API.
- **No clean free programmatic source.** Unlike TTF (yfinance) and storage (AGSI+/gie-py), the
  only free route to a PSV proxy is scraping GME pages / monthly ZIPs — fragile, and against
  the project's "clean sources, no fragile dependencies, reproducible" architecture.
- **Small signal for the access cost.** The basis is typically **+1 to +3 EUR/MWh** — a real
  Italian-specific signal, but a poor effort/value ratio versus alternatives that reuse data
  already in hand.

**Decision:** leave the basis as a documented gap rather than force a fragile or paid source.
If ever wired, the honest options are (a) a declared **Assumption** proxy (`PSV ≈ TTF + ~2`),
or (b) a real feed (ICE/ICIS) if a licence becomes available. The engineering point stands:
knowing which datum is *not* cleanly available — and choosing not to fake it — is part of the
provenance discipline, not a hole in it.
