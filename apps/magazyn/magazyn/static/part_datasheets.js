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
  let revision = 0, timer = null, busy = false, reviewed = null;
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
    for (const id of ["part-datasheet-sources","part-datasheet-review"]) {
      const box = $(id);
      if (box) { box.hidden = true; box.replaceChildren(); }
    }
    say("Wpisz pełne oznaczenie elementu.");
  }
  function isOpen() {
    return $("part-dialog")?.open === true;
  }
  function marking() {
    const form = $("part-form");
    const value = String(form?.elements.designation?.value || "").trim();
    // Numbers like 10k 0603 are ambiguous values, not full MPNs.
    return /^[a-z0-9][a-z0-9./_-]{3,59}$/i.test(value) &&
      /\d/.test(value) ? value : "";
  }
  function manufacturer() {
    return String($("part-form")?.elements.manufacturer?.value || "").trim();
  }

  async function find() {
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
    say("Wyszukuję dostępne dokumenty…");
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
        const btn = elem("button","Pobierz i przeanalizuj kartę PDF",row,"secondary small");
        btn.type = "button";
        btn.style.display = "block";
        btn.style.marginTop = "7px";
        btn.addEventListener("click", ()=>inspectToken(candidate.token));
        sources.appendChild(row);
      }
      const upload = elem("button","Analizuj wybrany PDF z telefonu",sources,"secondary small");
      upload.type="button";
      upload.addEventListener("click",inspectUploaded);
      // When a single *official* TI datasheet is the only result, prefetch
      // automatically after typing. Never auto-APPLY fields or inventory writes.
      // Multiple providers, unofficial sources and manually chosen files
      // always require operator selection.
      if (choices.length===1 && choices[0].source==="Texas Instruments" &&
          !($("part-form").elements.document.files?.length)) {
        say("Znaleziono oficjalną kartę TI. Pobieram ją do podglądu…");
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
    say("Pobieram i analizuję wybraną kartę katalogową…");
    try {
      const result = await api("/api/parts/datasheet/analyze",{
        method:"POST",body:JSON.stringify({token})
      });
      if (rev===revision && isOpen()) showReview(result);
    } catch (err) {
      if (rev===revision) say("Nie udało się pobrać PDF: "+String(err.message||"Błąd")+
                             ". Możesz dołączyć PDF ręcznie.");
    } finally {busy=false;}
  }

  async function inspectUploaded() {
    if (busy || !isOpen()) return;
    const file = $("part-form").elements.document.files?.[0];
    if (!file || !/\.pdf$/i.test(file.name)) {
      say("Wybierz najpierw kartę PDF w polu Dokumentacja techniczna.");
      return;
    }
    if (file.size > 8*1024*1024 || file.size < 100) {
      say("Karta PDF musi mieć maksymalnie 8 MB.");
      return;
    }
    const mpn=marking();
    if (!mpn) { say("Wpisz dokładne oznaczenie elementu."); return; }
    const rev=revision;
    busy=true;
    say("Analizuję wskazany PDF, bez wyszukiwania w Internecie…");
    try {
      const bytes = new Uint8Array(await file.arrayBuffer());
      let binary = "";
      for (let i=0;i<bytes.length;i+=8192) {
        binary += String.fromCharCode(...bytes.subarray(i,i+8192));
      }
      const result=await api("/api/parts/datasheet/analyze-upload",{
        method:"POST",body:JSON.stringify({marking:mpn,pdf_base64:btoa(binary)})
      });
      if (rev===revision && isOpen()) showReview(result,true);
    } catch (err) {
      if(rev===revision) say("Nie udało się odczytać PDF: "+String(err.message||"Błąd"));
    } finally{busy=false;}
  }

  function showReview(data,fromUserFile=false) {
    const review=$("part-datasheet-review");
    review.hidden=false;
    review.replaceChildren();
    reviewed = data;
    elem("strong","Propozycje danych z karty katalogowej",review);
    elem("p","Źródło: "+String(data.source_name||"PDF")+
      " · sprawdzono "+Number(data.pages_checked||0)+" stron.",review);
    if (data.source_url && /^https:\/\//i.test(data.source_url)) {
      const a=elem("a","Otwórz oryginalną kartę producenta",review);
      a.href=data.source_url;
      a.target="_blank";a.rel="noopener noreferrer";
    }
    for(const warning of Array.isArray(data.warnings)?data.warnings:[]) {
      const note=elem("p","⚠ "+String(warning).slice(0,250),review);
      note.style.color="#a74c22";
    }
    elem("p","Wartości są propozycjami. Wybierz pola i sprawdź cytat z PDF.",review);
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
      check.checked=!current && !data.family_datasheet &&
        candidate.confidence!=="verify_variant";
      const title=elem("span",names[candidate.field]||candidate.field,label);
      label.prepend(check);
      row.appendChild(label);
      const input=document.createElement("input");
      input.type="text";
      input.value=String(candidate.value||"").slice(0,160);
      input.maxLength=candidate.field.startsWith("spec_")?120:2000;
      input.style.width="100%";input.style.marginTop="6px";
      input.addEventListener("input",()=>{check.checked=true;});
      row.appendChild(input);
      if(current) elem("small","Wpisano wcześniej: "+current+" (bez nadpisywania).",row);
      elem("small","Strona "+(candidate.page||"—")+
        " · podstawa: "+String(candidate.evidence||"Źródło producenta").slice(0,180),row);
      list.appendChild(row);
    }
    if(!list.children.length)elem("p",
      "Brak parametrów jednoznacznie przypisanych do wariantu. Uzupełnij ręcznie.",review);
    const options=document.createElement("label");
    options.style.display="flex";options.style.gap="8px";options.style.marginTop="12px";
    const attach=document.createElement("input");
    attach.type="checkbox";
    attach.checked=!fromUserFile;
    options.append(attach,document.createTextNode("Dołącz pobrany PDF do nowego elementu"));
    if(!fromUserFile) review.appendChild(options);
    const actions=document.createElement("div");
    actions.style.display="flex";actions.style.gap="8px";
    actions.style.flexWrap="wrap";actions.style.marginTop="12px";
    const accept=elem("button","Zastosuj zaznaczone pola",actions,"primary");
    accept.type="button";
    accept.addEventListener("click",()=>{
      let n=0;
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
        } catch(_error) {
          say("Parametry zastosowano, ale nie udało się dołączyć PDF. Zrób to ręcznie.");
        }
      }
      reviewed=null;
      review.replaceChildren();
      elem("p","Zastosowano "+n+" pól."+
        (included?" Karta PDF została dołączona do formularza.":"")+
        " Sprawdź wartości i zapisz element osobnym przyciskiem.",review);
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
    review.scrollIntoView({behavior:"smooth",block:"nearest"});
  }

  document.addEventListener("DOMContentLoaded",()=>{
    const form=$("part-form"), dialog=$("part-dialog");
    if(!form||!dialog)return;
    $("part-datasheet-find").addEventListener("click",find);
    form.elements.designation.addEventListener("input",()=>{
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
      if(marking() && isOpen())void find();
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
