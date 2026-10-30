"use strict";

/* DEV: one approved datasheet -> evidence-backed suggestions in the EXISTING
 * electronic-component form. No database write before the normal Add button.
 * Online requests only go to our own authenticated Magazyn API.
 */
(function() {
  const allowed = new Set([
    "designation","primary_number","manufacturer","category","package",
    "spec_voltage","spec_current","spec_power","spec_resistance",
    "spec_capacitance","spec_tolerance","spec_pin_count",
    "spec_temperature","spec_interface","parameters",
  ]);
  const names = {
    designation:"Oznaczenie",primary_number:"Numer katalogowy producenta",
    manufacturer:"Producent",category:"Kategoria",package:"Obudowa",
    spec_voltage:"Napięcie",spec_current:"Prąd",spec_power:"Moc",
    spec_resistance:"Rezystancja",spec_capacitance:"Pojemność",
    spec_tolerance:"Tolerancja",spec_pin_count:"Liczba pinów",
    spec_temperature:"Temperatura pracy",spec_interface:"Interfejs / rodzina",
    parameters:"Dodatkowe parametry",
  };
  let revision = 0, timer = null, busy = false, reviewed = null, applying = false;
  let autoAnalyzeSelectedFile = false;
  let pdfDiskError = "";
  const $ = id => document.getElementById(id);

  function say(text) {
    const node = $("part-datasheet-status");
    if (node) node.textContent = text;
  }
  function elem(tag, text, parent, className) {
    const item = document.createElement(tag);
    item.textContent = text;
    if (className) item.className = className;
    if (parent) parent.appendChild(item);
    return item;
  }
  function clear() {
    revision++;
    clearTimeout(timer);
    busy = false;reviewed = null;
    pdfDiskError="";
    for (const id of ["part-datasheet-sources","part-datasheet-review"]) {
      const box = $(id);
      if (box) { box.hidden = true; box.replaceChildren(); }
    }
    updateSelectedPdfUi();
    say("Wpisz pełne oznaczenie elementu.");
  }
  function isOpen() {
    return $("part-dialog")?.open === true;
  }
  function marking() {
    const form = $("part-form");
    const value = String(form?.elements.designation?.value || "").trim();
    // Numbers like 10k 0603 are ambiguous values, not full MPNs.
    return /^[a-z0-9][a-z0-9./,_-]{3,59}$/i.test(value) &&
      /\d/.test(value) ? value : "";
  }
  function manufacturer() {
    return String($("part-form")?.elements.manufacturer?.value || "").trim();
  }

  function selectedPdf() {
    return $("part-form")?.elements.document?.files?.[0] || null;
  }
  function updateSelectedPdfUi() {
    const file=selectedPdf();
    const status=$("part-pdf-disk-status");
    const analyze=$("part-pdf-disk-analyze");
    if(!status || !analyze)return;
    const valid=!!file && /\.pdf$/i.test(file.name) &&
       file.size>=128 && file.size<=8*1024*1024;
    analyze.disabled=!valid || busy;
    status.classList.toggle("pdf-file-error",Boolean(pdfDiskError));
    if(pdfDiskError) {
      status.textContent=pdfDiskError;
      return;
    }
    if(!file) {
      status.textContent="Nie wybrano pliku PDF.";
    } else if(!/\.pdf$/i.test(file.name)) {
      status.textContent="Wybrano "+file.name+
        " — dokument zostanie dołączony po zapisie. Analizować można tylko PDF.";
    } else if(!valid) {
      status.textContent="Niepoprawny rozmiar PDF. Limit: od 128 B do 8 MB.";
    } else {
      status.textContent="Wybrano "+file.name+" ("+
        (file.size/(1024*1024)).toFixed(2)+" MB). PDF zostanie dołączony "+
        "po zapisaniu nowego elementu.";
    }
  }
  function resetPreview() {
    reviewed=null;
    const review=$("part-datasheet-review");
    if(review){review.hidden=true;review.replaceChildren();}
  }

  async function inspectMouser(mpn, rev, tme=null) {
    if (!isOpen() || rev!==revision || mpn!==marking()) return false;
    say("Sprawdzam dokładne oznaczenie w Mouser…");
    try {
      const data=await api("/api/parts/mouser/enrich",{
        method:"POST",body:JSON.stringify({query:mpn})
      });
      if (!isOpen() || rev!==revision || mpn!==marking()) return false;
      if(data.status!=="ok" || data.mpn.toUpperCase()!==mpn.toUpperCase()) {
        say(data.status==="ambiguous"
          ? "Mouser: kilka dokładnych wyników — wybierz wariant ręcznie."
          : "Mouser nie znalazł jednoznacznego MPN. Sprawdzam producenta.");
        return false;
      }
      const sources=$("part-datasheet-sources");
      const existing=sources.querySelector('[data-supplier-choice="mouser"]');
      if(!existing) {
        const btn=elem("button","Pokaż propozycje Mouser",sources,"secondary small");
        btn.type="button";
        btn.dataset.supplierChoice="mouser";
        btn.addEventListener("click",()=>{
          if(rev===revision && isOpen())showReview(data,false,false);
        });
      }
      if(tme && !sources.querySelector('[data-supplier-choice="tme"]')) {
        const btn=elem("button","Wróć do propozycji TME",sources,"secondary small");
        btn.type="button";
        btn.dataset.supplierChoice="tme";
        btn.addEventListener("click",()=>{
          if(rev===revision && isOpen())showReview(tme,false,false);
        });
      }
      showReview(data,false,!tme);
      say("Mouser: dokładny MPN. Sprawdź propozycje i dokumentację.");
      return true;
    }catch(_ignored){
      if(rev===revision && isOpen())say("Mouser niedostępny — można skorzystać z dokumentacji producenta.");
      return false;
    }
  }

  async function chooseCatalogVariant(variant, familyMpn, oldRev) {
    if (!isOpen() || oldRev!==revision || marking()!==familyMpn) return;
    if (!["tme","mouser"].includes(variant.supplier))return;
    const mpn=String(variant.mpn||"").trim();
    if (!/^[a-z0-9][a-z0-9./,_-]{3,59}$/i.test(mpn))return;

    const form=$("part-form");
    applying=true;
    try {
      // A different full part number is entered ONLY after the operator
      // has clicked a specific catalog variant.
      form.elements.designation.value=mpn;
      form.elements.designation.dispatchEvent(new Event("input",{bubbles:true}));
    }finally{applying=false;}
    clearTimeout(timer);
    const rev=++revision;
    reviewed=null;
    const review=$("part-datasheet-review");
    review.hidden=true;
    review.replaceChildren();
    const sources=$("part-datasheet-sources");
    sources.hidden=false;
    sources.replaceChildren();
    const back=elem("button","Wybierz inny wariant",sources,"secondary small");
    back.type="button";
    back.addEventListener("click",()=>{
      if(!isOpen() || rev!==revision || marking()!==mpn)return;
      applying=true;
      try {
        form.elements.designation.value=familyMpn;
        form.elements.designation.dispatchEvent(new Event("input",{bubbles:true}));
      }finally{applying=false;}
      clearTimeout(timer);
      void findAvailableVariants(familyMpn,++revision);
    });
    say("Wybrano "+mpn+". Pobieram dane z "+
      (variant.supplier==="tme"?"TME":"Mouser")+"…");
    try {
      const data=await api("/api/parts/"+variant.supplier+"/enrich",{
        method:"POST",body:JSON.stringify({query:mpn})
      });
      if (!isOpen() || rev!==revision || mpn!==marking())return;
      if (data.status!=="ok" || String(data.mpn||"").toUpperCase()!==mpn.toUpperCase()){
        say("Wybrany wariant nie zwrócił jednoznacznej karty katalogowej. "+
            "Spróbuj innego wariantu albo dodaj dane ręcznie.");
        return;
      }
      elem("strong","Wybrany wariant: "+mpn,sources,"part-variant-selected");
      showReview(data,false,false);
      say("Znaleziono dane "+mpn+". Zatwierdź wybrane pola przed dodaniem na stan.");
    }catch(_error){
      if(isOpen() && rev===revision)
        say("Nie udało się pobrać szczegółów wybranego wariantu. Spróbuj ponownie.");
    }
  }

  async function findAvailableVariants(mpn,rev) {
    if(!isOpen() || rev!==revision || marking()!==mpn)return false;
    say("Szukam dostępnych wariantów oznaczenia "+mpn+"…");
    let response;
    try {
      response=await api("/api/parts/suppliers/variants",{
        method:"POST",body:JSON.stringify({query:mpn})
      });
    }catch(_error){return false;}
    if(!isOpen() || rev!==revision || marking()!==mpn)return false;
    const variants=(Array.isArray(response.variants)?response.variants:[])
      .filter(item=>item && ["tme","mouser"].includes(item.supplier) &&
                    typeof item.mpn==="string" &&
                    /^[a-z0-9][a-z0-9./,_-]{3,59}$/i.test(item.mpn));
    if(!variants.length)return false;
    const sources=$("part-datasheet-sources");
    sources.hidden=false;
    sources.replaceChildren();
    const heading=elem("strong","Wybierz dokładny wariant "+mpn,sources);
    heading.className="part-variant-title";
    elem("p","TME i Mouser podają różne wersje tego układu. "+
         "Sprawdź oznaczenie na obudowie lub w dokumentacji i wybierz "+
         "pełny numer producenta. Nic nie zostanie wybrane automatycznie.",
         sources,"part-variant-note");
    const list=elem("div","",sources,"part-variants-list");
    for(const choice of variants) {
      const row=elem("div","",list,"part-variant-row");
      const information=elem("div","",row,"part-variant-info");
      elem("strong",choice.mpn,information);
      elem("small",(choice.supplier==="tme"?"TME":"Mouser")+" · "+
           String(choice.manufacturer||"Producent nieznany"),information);
      if(choice.description)elem("small",String(choice.description).slice(0,130),information);
      if(choice.supplier_sku && choice.supplier_sku!==choice.mpn)
        elem("small","Nr dostawcy: "+choice.supplier_sku,information);
      const btn=elem("button","Wybierz",row,"secondary small");
      btn.type="button";
      btn.setAttribute("aria-label","Wybierz wariant "+choice.mpn+
        " z "+(choice.supplier==="tme"?"TME":"Mouser"));
      btn.addEventListener("click",()=>{void chooseCatalogVariant(choice,mpn,rev);});
    }
    say("Znaleziono "+variants.length+" wariantów "+mpn+
        ". Wybierz numer zgodny z oznaczeniem elementu.");
    return true;
  }

  async function findManufacturerReference(mpn,rev) {
    if(!isOpen() || rev!==revision || marking()!==mpn)return false;
    say("Sprawdzam źródła producentów poza hurtowniami…");
    let data;
    try {
      data=await api("/api/parts/reference/fallback",{
        method:"POST",body:JSON.stringify({query:mpn})
      });
    }catch(_error){return false;}
    if(!isOpen() || rev!==revision || marking()!==mpn)return false;
    const candidates=Array.isArray(data.candidates)?data.candidates:[];
    if(!candidates.length)return false;
    const sources=$("part-datasheet-sources");
    sources.hidden=false;
    sources.replaceChildren();
    elem("strong","Możliwe dopasowanie poza hurtowniami",sources);
    elem("p","Producent nie potwierdził dokładnie oznaczenia "+mpn+
      ". Nie utożsamiamy podobnych numerów — zweryfikuj logo i obudowę.",sources);
    for(const candidate of candidates) {
      if(!candidate || !candidate.source_url ||
         typeof candidate.reference_mpn!=="string")continue;
      const row=elem("div","",sources,"manufacturer-reference-card");
      elem("strong",candidate.reference_mpn+" · "+
           String(candidate.manufacturer||""),row);
      elem("p",candidate.exact_mpn
        ? "Dokładny numer potwierdzony na stronie producenta."
        : "Podobny numer — końcówka oznaczenia wymaga weryfikacji.",row);
      const source=elem("a","Otwórz źródło producenta",row);
      source.href=candidate.source_url;
      source.target="_blank";source.rel="noopener noreferrer";
      const button=elem("button","Sprawdź proponowane pola",row,"secondary small");
      button.type="button";
      button.addEventListener("click",()=>{
        if(!isOpen() || rev!==revision || marking()!==mpn)return;
        // This does NOT replace the entered MPN or check uncertain fields.
        showReview(candidate,false,true);
        say("To tylko kandydat, nie potwierdzenie "+mpn+
          ". Przed zastosowaniem porównaj oznaczenie i obudowę.");
      });
    }
    say("Znaleziono "+candidates.length+
        " możliwych odniesień producenta. Żadne pola nie zostały zmienione.");
    return true;
  }

  async function find(skipTme=false) {
    const mpn = marking();
    if (!mpn || !isOpen()) {
      say("Wpisz pełne oznaczenie producenta (np. LM358 lub IRF3205).");
      return;
    }
    const rev = ++revision;
    const sources = $("part-datasheet-sources");
    sources.hidden = false;
    sources.replaceChildren();
    $("part-datasheet-review").hidden = true;
    $("part-datasheet-review").replaceChildren();
    reviewed = null;
    say(skipTme ? "Wyszukuję dokumentację producenta…" :
                  "Sprawdzam TME i dokumentację katalogową…");
    if (!skipTme) {
      try {
        // Only the authenticated Magazyn backend holds the TME credentials.
        const tme = await api("/api/parts/tme/enrich", {
          method:"POST",body:JSON.stringify({query:mpn})
        });
        if (!isOpen() || rev!==revision || mpn!==marking()) return;
        if (tme.status==="ok" && tme.mpn.toUpperCase()===mpn.toUpperCase()) {
          const row=document.createElement("div");
          row.className="supplier-result-row";
          elem("strong","TME API v2 · "+tme.mpn+" · "+
               (tme.manufacturer||"producent nieznany"),row);
          elem("p","Pobrano "+(tme.technical_parameters?.length||0)+
               " parametrów i "+(tme.documents?.length||0)+
               " dokumentów. Zatwierdź proponowane pola przed zapisaniem.",row);
          sources.appendChild(row);
          const compare=elem("button","Porównaj z Mouser",sources,"secondary small");
          compare.type="button";
          compare.addEventListener("click",()=>{void inspectMouser(mpn,rev,tme);});
          const btn=elem("button","Sprawdź alternatywną kartę producenta",
                         sources,"secondary small");
          btn.type="button";
          btn.addEventListener("click",()=>find(true));
          showReview(tme,false,false);
          say("TME: dopasowanie numeru potwierdzone. Możesz też porównać dane z Mouser.");
          return;
        }
        if (tme.status==="ambiguous") {
          say("TME: kilka produktów z tym samym MPN — wymagany wybór wariantu.");
        }
      } catch (_ignored) {
        // A supplier outage never disables the established PDF/manufacturer flow.
      }
    }
    if(!skipTme) {
      // Mouser is a fallback when TME does not return an exact catalog match.
      // TME success above deliberately does NOT spend a Mouser API request.
      if(await inspectMouser(mpn,rev))return;
      if (!isOpen() || rev!==revision || mpn!==marking()) return;
    }
    if(!skipTme) {
      // A family number may have NO exact product, while distributor APIs
      // return several different (package/ordering) versions. Require an
      // explicit user choice; never silently select a suffix.
      if(await findAvailableVariants(mpn,rev))return;
      if (!isOpen() || rev!==revision || mpn!==marking()) return;
      if(await findManufacturerReference(mpn,rev))return;
      if (!isOpen() || rev!==revision || mpn!==marking()) return;
    }
    say("Wyszukuję dostępne dokumenty producenta…");
    try {
      const params = new URLSearchParams({marking:mpn,manufacturer:manufacturer()});
      const result = await api("/api/parts/datasheet/search?"+params);
      if (!isOpen() || rev!==revision || mpn!==marking()) return;
      const choices = Array.isArray(result.candidates) ? result.candidates : [];
      if (!choices.length) {
        say("Brak zweryfikowanej karty online. Możesz wybrać PDF ręcznie.");
      } else {
        say("Znaleziono źródła: "+choices.length+". Wybierz właściwego producenta.");
      }
      for (const candidate of choices) {
        const row = document.createElement("div");
        row.style.margin = "8px 0";
        row.style.border = "1px solid #e7dacd";
        row.style.borderRadius = "8px";
        row.style.padding = "10px";
        elem("strong", String(candidate.part_number || mpn), row);
        elem("p", String(candidate.source || "") +
          " · "+String(candidate.manufacturer || "") +
          " · "+String(candidate.domain || ""), row);
        elem("small","Sprawdź producenta i wariant obudowy przed analizą.",row);
        const label=candidate.document_kind==="manufacturer_product"
          ? "Odczytaj oficjalne parametry producenta"
          : "Pobierz i przeanalizuj kartę PDF";
        const btn = elem("button",label,row,"secondary small");
        btn.type = "button";
        btn.style.display = "block";
        btn.style.marginTop = "7px";
        btn.addEventListener("click", ()=>inspectToken(candidate.token));
        sources.appendChild(row);
      }
      const upload = elem("button","Otwórz analizę PDF z dysku",sources,"secondary small");
      upload.type="button";
      upload.addEventListener("click",()=>{
        const tool=$("part-pdf-disk-tool");
        tool.open=true;
        tool.scrollIntoView({behavior:"instant",block:"center"});
      });
      // Official manufacturer sources can be read automatically after typing.
      // Nothing is copied to inventory or stored until user confirmation.
      if (choices.length===1 &&
          (choices[0].source==="Texas Instruments" ||
           choices[0].source==="Infineon — oficjalna karta produktu") &&
          !($("part-form").elements.document.files?.length)) {
        say("Znaleziono oficjalne dane producenta. Analizuję do podglądu…");
        void inspectToken(choices[0].token);
      }
    } catch (_error) {
      if (rev !== revision || !isOpen()) return;
      sources.replaceChildren();
      say("Serwis dokumentacji niedostępny. Użyj własnego pliku PDF.");
    }
  }

  async function inspectToken(token) {
    const rev = revision;
    if (busy || !isOpen()) return;
    busy = true;
    say("Pobieram i analizuję dane producenta…");
    try {
      const result = await api("/api/parts/datasheet/analyze",{
        method:"POST",body:JSON.stringify({token})
      });
      if (rev===revision && isOpen()) showReview(result);
    } catch (err) {
      if (rev===revision) say("Nie udało się odczytać danych: "+String(err.message||"Błąd")+
                             ". Możesz dołączyć PDF ręcznie.");
    } finally {busy=false;}
  }

  async function inspectLink() {
    if(busy || !isOpen())return;
    const mpn=marking();
    const input=$("part-pdf-link");
    const url=String(input?.value||"").trim();
    if(!mpn){say("Najpierw wpisz pełne oznaczenie elementu.");return;}
    if(!/^https:\/\//i.test(url)) {
      say("Podaj poprawny link HTTPS do PDF producenta.");
      $("part-pdf-link-tool").open=true;
      input.focus();
      return;
    }
    clearTimeout(timer);
    const rev=++revision;
    resetPreview();
    const sources=$("part-datasheet-sources");
    sources.hidden=true;sources.replaceChildren();
    busy=true;
    const button=$("part-pdf-link-analyze");
    button.disabled=true;
    say("Pobieram PDF i sprawdzam oznaczenie "+mpn+"…");
    try {
      const result=await api("/api/parts/datasheet/analyze-link",{
        method:"POST",body:JSON.stringify({marking:mpn,pdf_url:url})
      });
      if(rev!==revision || !isOpen() || marking()!==mpn || input.value.trim()!==url)return;
      showReview(result,false,true);
      say("PDF zweryfikowany. Zaznacz pola i opcję dołączenia PDF przed zapisem.");
    }catch(error) {
      if(rev===revision && isOpen())
        say("Nie udało się odczytać PDF z linku: "+
            String(error.message||"Błąd dokumentu").slice(0,210));
    }finally {
      busy=false;button.disabled=false;updateSelectedPdfUi();
    }
  }

  function showUnmatchedPdf(data) {
    const review=$("part-datasheet-review");
    review.replaceChildren();
    review.hidden=false;
    reviewed=null;
    elem("strong","PDF odczytany — numer elementu nie został potwierdzony",review);
    elem("p","Wpisany numer: "+String(data.part_number||"")+
      ". Plik otwarto i odczytano, ale nie ma w nim tego dokładnego oznaczenia.",review);
    if(data.extraction_mode==="ocr")
      elem("p","Zastosowano lokalny OCR. Zweryfikuj oznaczenia w oryginalnym skanie.",review);
    const alternatives=Array.isArray(data.candidate_numbers)?data.candidate_numbers:[];
    if(alternatives.length)
      elem("p","W dokumencie znaleziono podobne oznaczenie: "+
        alternatives.join(", ")+". To nie dowodzi zgodności elementów.",review);
    elem("p","Sprawdź numer na obudowie i wprowadź właściwe oznaczenie, "+
      "a następnie wybierz ponownie Analizuj wybrany PDF. Nie uzupełniamy "+
      "parametrów innego układu.",review);
    if(selectedPdf())
      elem("p","PDF z dysku pozostał wybrany w formularzu jako załącznik. "+
        "Nie został jeszcze zapisany do Magazynu.",review);
    const button=elem("button","Analizuj ponownie po poprawieniu numeru",review,"secondary");
    button.type="button";
    button.addEventListener("click",()=>{void inspectUploaded();});
    review.scrollIntoView({behavior:"instant",block:"nearest"});
  }

  async function inspectUploaded() {
    if(busy || !isOpen())return;
    const file=selectedPdf();
    const mpn=marking();
    if(!mpn){say("Najpierw wpisz pełne oznaczenie elementu.");return;}
    if(!file || !/\.pdf$/i.test(file.name)) {
      $("part-pdf-disk-tool").open=true;
      say("Wybierz najpierw plik PDF z dysku lub telefonu.");return;
    }
    if(file.size>8*1024*1024 || file.size<128){
      say("PDF musi mieć rozmiar od 128 B do 8 MB.");return;
    }
    clearTimeout(timer);
    const rev=++revision;
    resetPreview();
    const sources=$("part-datasheet-sources");
    sources.hidden=true;sources.replaceChildren();
    pdfDiskError="";
    busy=true;updateSelectedPdfUi();
    say("Sprawdzam dokument "+file.name+" i numer "+mpn+"…");
    try {
      const header=await file.slice(0,5).text();
      if(file.size<128 || header!=="%PDF-")
        throw new Error("Wybrany plik nie jest poprawnym PDF.");
      // Native FileReader avoids large intermediate JS strings and works
      // more reliably on Android phones than manual String.fromCharCode loops.
      const pdf_base64=await new Promise((resolve,reject)=>{
        const reader=new FileReader();
        reader.onerror=()=>reject(new Error("Nie udało się odczytać pliku z urządzenia."));
        reader.onabort=()=>reject(new Error("Odczyt PDF został przerwany."));
        reader.onload=()=>{
          const contents=String(reader.result||"");
          const comma=contents.indexOf(",");
          if(comma<0)return reject(new Error("Nieprawidłowy odczyt pliku PDF."));
          resolve(contents.slice(comma+1));
        };
        reader.readAsDataURL(file);
      });
      say("Plik przesłany. Analizuję tekst i, jeśli trzeba, uruchamiam lokalny OCR…");
      const result=await api("/api/parts/datasheet/analyze-upload",{
        method:"POST",body:JSON.stringify({marking:mpn,pdf_base64})
      });
      const latest=selectedPdf();
      const sameFile=latest && latest.name===file.name &&
        latest.size===file.size && latest.lastModified===file.lastModified;
      if(rev!==revision || !isOpen() || marking()!==mpn || !sameFile)return;
      if(result.status==="needs_identification") {
        showUnmatchedPdf(result);
        say("PDF odczytany, ale nie potwierdzono numeru "+mpn+
            ". Sprawdź oznaczenie; plik pozostaje wybrany jako załącznik.");
        return;
      }
      showReview(result,true,true);
      say(result.extraction_mode==="ocr"
        ? "PDF odczytany przez OCR. Sprawdź proponowane pola; plik dołączy się przy zapisie."
        : "PDF odczytany. Zatwierdź wybrane pola; plik dołączy się przy zapisie elementu.");
    }catch(error) {
      if(rev===revision && isOpen()) {
        pdfDiskError="Błąd analizy: "+
          String(error.message||"Nie udało się odczytać PDF").slice(0,195);
        say(pdfDiskError);
      }
    }finally{busy=false;updateSelectedPdfUi();}
  }

  function showReview(data,fromUserFile=false,scrollToReview=true) {
    const review=$("part-datasheet-review");
    review.hidden=false;
    review.replaceChildren();
    reviewed = data;
    const productPage=data.source_kind==="manufacturer_product";
    const manufacturerReference=data.source_kind==="manufacturer_reference";
    const supplierCatalog=data.source_kind==="supplier_catalog";
    const supplierName=String(data.source_name||"hurtownia").slice(0,70);
    const supplierShort=supplierName.startsWith("Mouser")?"Mouser":"TME";
    elem("strong",supplierCatalog
      ? "Parametry z "+supplierShort+" — propozycje do zatwierdzenia"
      : manufacturerReference ? "Możliwy model — weryfikacja oznaczenia"
      : productPage ? "Propozycje danych z oficjalnej karty produktu"
      : "Propozycje danych z karty katalogowej",review);
    elem("p","Źródło: "+String(data.source_name||"PDF")+
      (supplierCatalog ? " · dokładny MPN: "+String(data.mpn||"") :
       manufacturerReference ? " · znaleziono "+String(data.reference_mpn||"")+
         " zamiast "+String(data.requested_mpn||"") :
       productPage ? " · karta produktu producenta" :
       " · sprawdzono "+Number(data.pages_checked||0)+" stron PDF."),review);
    if(data.extraction_mode==="ocr")
      elem("p","PDF został odczytany lokalnie przez OCR. Wyniki mogą zawierać "+
        "błędy rozpoznania; wszystkie propozycje należy sprawdzić przed użyciem.",review);
    if (data.source_url && /^https:\/\//i.test(data.source_url)) {
      const a=elem("a",manufacturerReference
        ? "Otwórz źródło producenta"
        : "Otwórz oryginalną kartę producenta",review);
      a.href=data.source_url;
      a.target="_blank";a.rel="noopener noreferrer";
    }
    if (productPage && /^https:\/\/www\.infineon\.com\/assets\/.*\.pdf$/i.test(
        String(data.datasheet_url||""))) {
      const a=elem("a","Otwórz datasheet PDF producenta",review);
      a.href=data.datasheet_url;
      a.target="_blank";a.rel="noopener noreferrer";
      a.style.display="block";
    }
    if(supplierCatalog) {
      const docs=Array.isArray(data.documents)?data.documents:[];
      const heading=elem("strong","Dokumentacja "+supplierShort+" ("+docs.length+")",review);
      heading.style.display="block";
      heading.style.marginTop="10px";
      if(!docs.length)elem("p",supplierShort+" nie udostępnił dokumentów dla tego produktu.",review);
      for(const doc of docs) {
        let url;
        try {url=new URL(String(doc.url||""));}catch {continue;}
        const allowedHosts=supplierShort==="TME"
          ? ["www.tme.eu"] : ["www.mouser.com","www.mouser.pl"];
        if(url.protocol!=="https:" || !allowedHosts.includes(url.hostname))continue;
        const a=elem("a","Otwórz "+String(doc.filename||"dokument")+
          " · "+String(doc.language||"")+" · "+supplierShort,review);
        a.href=url.href;
        a.target="_blank";a.rel="noopener noreferrer";
        a.style.display="block";
        a.style.margin="5px 0";
      }
      if(supplierShort==="Mouser" && data.product_url) {
        try {
          const productUrl=new URL(data.product_url);
          if(productUrl.protocol==="https:" &&
             ["www.mouser.com","www.mouser.pl"].includes(productUrl.hostname)) {
            const a=elem("a","Otwórz kartę produktu Mouser",review);
            a.href=productUrl.href;a.target="_blank";a.rel="noopener noreferrer";
            a.style.display="block";
          }
        } catch {}
      }
      if(data.availability)elem("p","Dostępność katalogowa: "+String(data.availability),review);
      elem("p","Dokumenty pozostają na serwerach dostawców — niczego nie kopiujemy automatycznie do bazy.",review);
      const technical=Array.isArray(data.technical_parameters)?data.technical_parameters:[];
      if(technical.length) {
        const details=document.createElement("details");
        const summary=elem("summary","Atrybuty katalogowe "+supplierShort+" ("+
          technical.length+")",details);
        summary.style.cursor="pointer";
        for(const parameter of technical) {
          elem("p",String(parameter.name||"")+": "+String(parameter.value||""),details);
        }
        review.appendChild(details);
      }
    }
    for(const warning of Array.isArray(data.warnings)?data.warnings:[]) {
      const note=elem("p","⚠ "+String(warning).slice(0,250),review);
      note.style.color="#a74c22";
    }
    elem("p",manufacturerReference
      ? "To NIE jest potwierdzona identyfikacja wpisanego elementu. Pola pozostają odznaczone; przed ich użyciem sprawdź logo, obudowę i pełny numer na układzie."
      : supplierCatalog
      ? "Dane katalogowe "+supplierShort+" wymagają sprawdzenia wariantu. Zaznacz odpowiednie pola — nic nie trafi na stan bez osobnego zapisu."
      : productPage ? "Wartości pochodzą ze strukturalnych danych producenta. Zweryfikuj parametry i wariant przed zatwierdzeniem."
      : "Wartości są propozycjami. Wybierz pola i sprawdź cytat z PDF.",review);
    const form=$("part-form");
    const list=document.createElement("div");
    list.id="part-datasheet-fields";
    review.appendChild(list);
    const suggestions=(Array.isArray(data.suggestions)?data.suggestions:[])
      .filter(x=>x && allowed.has(x.field));
    for (const candidate of suggestions) {
      const original=form.elements.namedItem(candidate.field);
      if(!original)continue;
      const current=String(original.value||"").trim();
      const row=document.createElement("div");
      row.dataset.partField=candidate.field;
      row.style.padding="8px 0";
      row.style.borderBottom="1px solid #e8e1da";
      const label=document.createElement("label");
      label.style.display="flex";label.style.gap="8px";
      const check=document.createElement("input");
      check.type="checkbox";
      const verifiedIdentity=["primary_number","manufacturer"].includes(candidate.field) &&
        candidate.confidence==="source" && !manufacturerReference;
      check.checked=!current && (!data.family_datasheet || verifiedIdentity) &&
        candidate.confidence!=="verify_variant";
      const title=elem("span",names[candidate.field]||candidate.field,label);
      label.prepend(check);
      row.appendChild(label);
      const input=document.createElement("input");
      input.type="text";
      input.maxLength=candidate.field.startsWith("spec_")?120:
        (candidate.field==="parameters"?2000:200);
      input.value=String(candidate.value||"").slice(0,input.maxLength);
      input.style.width="100%";input.style.marginTop="6px";
      input.addEventListener("input",()=>{check.checked=true;});
      row.appendChild(input);
      if(current) elem("small","Wpisano wcześniej: "+current+" (bez nadpisywania).",row);
      const provenance=(manufacturerReference ? "Strona producenta" :
        supplierCatalog ? supplierName : productPage ? "Karta produktu" :
        candidate.page ? "Strona "+candidate.page : "Potwierdzone źródło");
      elem("small",provenance+
        " · podstawa: "+String(candidate.evidence||"Źródło producenta").slice(0,180),row);
      list.appendChild(row);
    }
    if(!list.children.length)elem("p",
      "Brak parametrów jednoznacznie przypisanych do wariantu. Uzupełnij ręcznie.",review);
    const options=document.createElement("label");
    options.style.display="flex";options.style.gap="8px";options.style.marginTop="12px";
    const attach=document.createElement("input");
    attach.type="checkbox";
    const hasDownloadedPdf=!fromUserFile && Boolean(data.pdf_base64);
    const existing=selectedPdf();
    attach.checked=hasDownloadedPdf && !existing;
    options.append(attach,document.createTextNode(existing
      ? "Dołącz PDF z linku (zastąpi obecnie wybrany plik)"
      : "Dołącz pobrany PDF do nowego elementu"));
    if(hasDownloadedPdf) review.appendChild(options);
    if(fromUserFile || data.document_already_selected)
      elem("p","Wybrany PDF z dysku pozostaje w formularzu i zostanie "+
        "dołączony dopiero po kliknięciu Dodaj element.",review);
    const actions=document.createElement("div");
    actions.style.display="flex";actions.style.gap="8px";
    actions.style.flexWrap="wrap";actions.style.marginTop="12px";
    const accept=elem("button","Zastosuj zaznaczone pola",actions,"primary");
    accept.type="button";
    accept.addEventListener("click",()=>{
      let n=0;
      applying=true;
      for(const row of list.children) {
        const field=row.dataset.partField;
        const selected=row.querySelector("input[type=checkbox]");
        const editor=row.querySelector("input[type=text]");
        const target=form.elements.namedItem(field);
        if(!selected?.checked||!editor||!target)continue;
        const value=editor.value.trim();
        if(!value||target.value===value)continue;
        target.value=value;
        target.dispatchEvent(new Event("input",{bubbles:true}));
        target.dispatchEvent(new Event("change",{bubbles:true}));
        n++;
      }
      applying=false;
      let included=false;
      if(attach.checked && !fromUserFile && reviewed?.pdf_base64) {
        try {
          const binary=atob(reviewed.pdf_base64);
          const bytes=new Uint8Array(binary.length);
          for(let i=0;i<binary.length;i++)bytes[i]=binary.charCodeAt(i);
          const file=new File([bytes],String(reviewed.filename||"datasheet.pdf"),
                              {type:"application/pdf"});
          const dt=new DataTransfer();
          dt.items.add(file);
          form.elements.document.files=dt.files;
          form.elements.doc_type.value="datasheet";
          included=true;
          updateSelectedPdfUi();
        } catch(_error) {
          say("Parametry zastosowano, ale nie udało się dołączyć PDF. Zrób to ręcznie.");
        }
      }
      reviewed=null;
      review.replaceChildren();
      elem("p","Zastosowano "+n+" pól."+
        (included?" Karta PDF jest wybrana jako załącznik.":"")+
        (selectedPdf()?" Wybrany dokument zostanie dołączony przy zapisie elementu.":"")+
        " Sprawdź wartości i kliknij Dodaj element, aby zapisać produkt.",review);
      if(typeof schedulePartSimilar==="function")schedulePartSimilar();
    });
    const cancel=elem("button","Odrzuć propozycje",actions,"secondary");
    cancel.type="button";
    cancel.addEventListener("click",()=>{
      reviewed=null;review.hidden=true;review.replaceChildren();
      say("Odrzucono propozycje. Formularz pozostał niezmieniony.");
    });
    review.appendChild(actions);
    say("Karta gotowa. Sprawdź proponowane pola.");
    if(scrollToReview)review.scrollIntoView({behavior:"smooth",block:"nearest"});
  }

  document.addEventListener("DOMContentLoaded",()=>{
    const form=$("part-form"), dialog=$("part-dialog");
    if(!form||!dialog)return;
    $("part-datasheet-find").addEventListener("click",()=>find());
    $("part-pdf-link-analyze").addEventListener("click",inspectLink);
    $("part-pdf-disk-analyze").addEventListener("click",inspectUploaded);
    $("part-pdf-disk-choose").addEventListener("click",()=>{
      if(!isOpen())return;
      autoAnalyzeSelectedFile=true;
      form.elements.document.click();
    });
    form.elements.document.addEventListener("change",()=>{
      pdfDiskError="";
      const automatic=autoAnalyzeSelectedFile;
      autoAnalyzeSelectedFile=false;
      clearTimeout(timer);
      revision++;
      resetPreview();
      updateSelectedPdfUi();
      const file=selectedPdf();
      if(file){
        $("part-pdf-disk-tool").open=true;
        say(/\.pdf$/i.test(file.name)
          ? "Wybrano "+file.name+". "+(automatic
              ? "Rozpoczynam analizę PDF…" : "Kliknij Analizuj wybrany PDF.")
          : "Wybrano załącznik "+file.name+". Analiza jest dostępna dla PDF.");
        if(automatic && /\.pdf$/i.test(file.name) &&
           file.size>=128 && file.size<=8*1024*1024 && marking())
          Promise.resolve().then(()=>inspectUploaded());
      }
    });
    form.elements.document.addEventListener("cancel",()=>{
      autoAnalyzeSelectedFile=false;
    });
    $("part-pdf-link").addEventListener("input",()=>{
      if(reviewed?.source_kind==="manufacturer_pdf"){
        revision++;resetPreview();
        say("Link PDF się zmienił. Przeanalizuj nowy dokument.");
      }
    });
    form.elements.designation.addEventListener("input",()=>{
      if(applying)return;
      clearTimeout(timer);
      revision++;
      reviewed=null;
      const panel=$("part-datasheet-review");
      panel.hidden=true;
      panel.replaceChildren();
      const results=$("part-datasheet-sources");
      results.hidden=true;
      results.replaceChildren();
      const mpn=marking();
      if(mpn && isOpen())timer=setTimeout(find,1100);
    });
    form.elements.manufacturer.addEventListener("change",()=>{
      if(!applying && marking() && isOpen())void find();
    });
    form.addEventListener("submit",function(event){
      if(!busy && !reviewed)return;
      event.preventDefault();
      event.stopImmediatePropagation();
      say(busy ? "Zakończ analizę karty przed zapisem." :
        "Najpierw zastosuj albo odrzuć propozycje dokumentacji.");
      $("part-datasheet-review").scrollIntoView({behavior:"smooth",block:"nearest"});
    },true);
    dialog.addEventListener("close",clear);
    window.magazynPartDatasheet={reset:clear};
  });
})();
