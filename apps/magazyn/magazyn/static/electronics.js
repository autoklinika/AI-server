"use strict";

/* Electronics-only WebGUI. Shared Magazyn API, sessions and CSRF; no separate app. */
const electronicSpecLabels = Object.freeze({
  voltage:"Napięcie",current:"Prąd",power:"Moc",resistance:"Rezystancja",
  capacitance:"Pojemność",tolerance:"Tolerancja",pin_count:"Liczba pinów",
  temperature:"Temperatura pracy",interface:"Interfejs / rodzina",
});
const electronicDocumentLabels = Object.freeze({
  datasheet:"Karta katalogowa",schematic:"Schemat",other:"Dokumentacja",
});
let electronicCandidates=[], electronicRevision=0, electronicTimer=null;

function partData(form){
  const values=Object.fromEntries(new FormData(form).entries());
  const specs={};
  for(const key of Object.keys(electronicSpecLabels))specs[key]=(values["spec_"+key]||"").trim();
  return {
    kind:"part", designation:(values.designation||"").trim(),
    primary_number:(values.primary_number||"").trim(),
    manufacturer:(values.manufacturer||"").trim(),
    category:(values.category||"").trim(),
    package:(values.package||"").trim(),
    parameters:(values.parameters||"").trim(),
    notes:(values.notes||"").trim(),
    specs,model:"",brand:"",hw:"",sw:"",
    numbers:splitNumbers(values.numbers).map(number=>({number,number_type:"other"})),
    location_id:Number(values.location_id)||null,
    new_location_code:!locations.length?byId("part-location-code").value.trim():"",
    new_location_description:!locations.length?byId("part-location-description").value.trim():"",
    quantity:Number(values.quantity),product_state:"na",technical_state:"na",
    allow_distinct_variant:byId("part-allow-variant").checked,
  };
}
function openPartDialog(){
  if(!session)return;
  if(!locations.length&&session.role!=="admin")
    return toast("Administrator musi najpierw utworzyć lokalizację.",true);
  const form=byId("part-form");
  form.reset();
  if(window.magazynPartDatasheet)window.magazynPartDatasheet.reset();
  byId("part-quantity").value="1";
  byId("part-location").innerHTML=locationOptions();
  const firstLocation=!locations.length;
  byId("part-location").required=!firstLocation;
  byId("part-location").disabled=firstLocation;
  byId("part-location-panel").hidden=!firstLocation;
  byId("part-first-location-help").hidden=!firstLocation;
  byId("part-location-toggle").hidden=firstLocation;
  byId("part-location-code").required=firstLocation;
  byId("part-location-save").hidden=firstLocation;
  byId("part-similar-box").hidden=true;
  byId("part-allow-variant").checked=false;
  byId("part-order-create-quantity-label").hidden=true;
  electronicCandidates=[];electronicRevision++;clearTimeout(electronicTimer);
  // One submit can create the first location and the product atomically.
  byId("part-submit").disabled=false;
  byId("part-dialog").showModal();
  requestAnimationFrame(()=>form.elements.designation.focus());
}
function schedulePartSimilar(){
  clearTimeout(electronicTimer);
  electronicRevision++;
  if(!byId("part-dialog").open)return;
  const data=partData(byId("part-form"));
  if(data.primary_number.length<4&&data.designation.length<3){
    electronicCandidates=[];renderPartSimilar();return;
  }
  electronicTimer=setTimeout(loadPartSimilar,360);
}
async function loadPartSimilar(){
  if(!byId("part-dialog").open)return;
  const revision=++electronicRevision;
  const data=partData(byId("part-form"));
  const params=new URLSearchParams();
  for(const key of ["kind","designation","primary_number","manufacturer",
                     "category","package","parameters"])if(data[key])params.set(key,data[key]);
  params.set("specs_json",JSON.stringify(data.specs));
  try{
    const rows=await api("/api/items/similar?"+params);
    if(revision!==electronicRevision||!byId("part-dialog").open)return;
    electronicCandidates=rows;renderPartSimilar();
  }catch(e){if(revision===electronicRevision)toast(e.message,true);}
}
function renderPartSimilar(){
  const box=byId("part-similar-box"),list=byId("part-similar-list");
  const checkbox=byId("part-allow-variant");
  if(!electronicCandidates.length){
    checkbox.checked=false;box.hidden=true;
    // One submit can create the first location and the product atomically.
  byId("part-submit").disabled=false;
    return;
  }
  box.hidden=false;
  const exact=electronicCandidates.some(p=>p.same_variant);
  byId("part-similar-spinner").textContent=exact?"Istniejący wariant":"Podobny element";
  list.innerHTML=electronicCandidates.map(p=>
    '<div class="similar-item"><span><strong>'+esc(p.designation)+'</strong>'+
    '<small>'+esc(p.primary_number||"Brak numeru")+' · '+fmt(p.quantity)+' szt.</small></span>'+
    '<button type="button" class="small select-existing-part" data-id="'+p.id+
    '">Otwórz istniejący</button></div>').join("");
  byId("part-allow-variant-label").hidden=exact;
  if(exact)checkbox.checked=false;
  byId("part-submit").disabled=exact||!checkbox.checked;
}
async function fileToBase64(file){
  if(!file)return null;
  if(file.size<1||file.size>8*1024*1024)
    throw new Error("Dokument musi mieć od 1 bajta do 8 MB.");
  if(!/\.(pdf|png|jpe?g)$/i.test(file.name))
    throw new Error("Wybierz dokument PDF, PNG lub JPG.");
  const bytes=new Uint8Array(await file.arrayBuffer());
  let binary="";
  for(let pos=0;pos<bytes.length;pos+=8192){
    binary+=String.fromCharCode(...bytes.subarray(pos,pos+8192));
  }
  return btoa(binary);
}
async function sendElectronicDocument(itemId,file,docType){
  if(!file)return null;
  const base64=await fileToBase64(file);
  return api("/api/items/"+itemId+"/documents",{
    method:"POST",body:JSON.stringify({
      filename:file.name,doc_type:docType,content_base64:base64,
    }),
  });
}
async function savePart(event){
  event.preventDefault();
  if(!session)return;
  const form=event.currentTarget;
  const data=partData(form);
  if(!data.designation||!data.category)return toast("Podaj oznaczenie i kategorię elementu.",true);
  if(!Number.isSafeInteger(data.quantity)||data.quantity<0||data.quantity>2_000_000_000)
    return toast("Nieprawidłowa liczba sztuk.",true);
  if(!data.location_id&&!data.new_location_code){
    toast("Wpisz kod pierwszej lokalizacji, np. A1.",true);
    byId("part-location-panel").hidden=false;
    byId("part-location-code").focus();
    return;
  }
  if(electronicCandidates.some(p=>p.same_variant))
    return toast("Taki wariant istnieje. Otwórz produkt i zwiększ jego stan.",true);
  if(electronicCandidates.length&&!data.allow_distinct_variant)
    return toast("Potwierdź świadome dodanie osobnego wariantu.",true);
  const file=form.elements.document.files[0]||null;
  if(file&&(file.size>8*1024*1024||!/\.(pdf|png|jpe?g)$/i.test(file.name)))
    return toast("Wybierz plik PDF/PNG/JPG nie większy niż 8 MB.",true);
  const ordered=session.role==="admin"&&byId("part-order-on-create").checked;
  const orderQty=Number(byId("part-order-create-quantity").value);
  if(ordered&&(!Number.isSafeInteger(orderQty)||orderQty<1||orderQty>2_000_000_000))
    return toast("Podaj poprawną ilość zamówioną.",true);
  const button=byId("part-submit");button.disabled=true;
  let created;
  try{
    created=await api("/api/items/receive",{method:"POST",body:JSON.stringify(data)});
  }catch(e){
    toast(e.message,true);button.disabled=false;
    if(e.message.includes("istnieje")||e.message.includes("podobn")||e.message.includes("wariant"))
      loadPartSimilar();
    return;
  }
  // Product and receipt commit first. Secondary upload failure is explicit and recoverable.
  const problems=[];
  if(file){
    try{await sendElectronicDocument(created.id,file,form.elements.doc_type.value);}
    catch(e){problems.push("dokument: "+e.message);}
  }
  if(ordered){
    try{await api("/api/items/"+created.id+"/order-status",{
      method:"PUT",body:JSON.stringify({status:"ordered",quantity:orderQty,note:""}),
    });}
    catch(e){problems.push("status zamówienia: "+e.message);}
  }
  byId("part-dialog").close();
  if(data.new_location_code)await loadLocations();
  await Promise.all([loadItems(),loadStats(),loadBrands()]);
  if(problems.length){
    toast("Element zapisany, ale nie udało się zapisać: "+problems.join("; ")+
          ". Dodaj brakujące dane w szczegółach.",true);
    openItem(created.id);
  }else toast("Dodano element elektroniczny"+(file?" i dokumentację":"")+
              (ordered?" (Zamówione)":"")+".");
}
async function savePartLocation(){
  if(session?.role!=="admin")return;
  const code=byId("part-location-code").value.trim();
  if(!code)return toast("Podaj oznaczenie lokalizacji.",true);
  const button=byId("part-location-save");button.disabled=true;
  try{
    const created=await api("/api/locations",{method:"POST",body:JSON.stringify({
      code,description:byId("part-location-description").value.trim(),
    })});
    await loadLocations();byId("part-location").value=String(created.id);
    byId("part-location-panel").hidden=true;
    toast("Dodano lokalizację "+code);
    renderPartSimilar();loadStats();
  }catch(e){toast(e.message,true);}
  finally{button.disabled=false;}
}
function renderPurchaseStatus(details){
  const value=details.order_status||{status:"none",quantity:0,note:""};
  if(session?.role!=="admin")return;
  const form=byId("order-status-form");
  form.dataset.itemId=String(details.id);
  form.elements.status.value=value.status;
  form.elements.quantity.value=String(value.quantity||1);
  form.elements.note.value=value.note||"";
  const delivery=byId("order-delivery-form");
  delivery.hidden=value.status!=="ordered";
  delivery.dataset.itemId=String(details.id);
  delivery.elements.location_id.innerHTML=locationOptions();
  delivery.elements.quantity.max=String(value.quantity||1);
  delivery.elements.quantity.value=String(value.quantity||1);
  byId("order-delivery-ecu-fields").hidden=details.kind!=="ecu";
  updatePurchaseInputs();
}
function updatePurchaseInputs(){
  const form=byId("order-status-form"),ordered=form.elements.status.value==="ordered";
  byId("order-quantity-wrap").hidden=!ordered;
  form.elements.quantity.required=ordered;
  form.elements.note.disabled=!ordered;
}
async function receiveOrderedDelivery(event){
  event.preventDefault();
  const form=event.currentTarget;
  if(session?.role!=="admin"||!chosen||form.dataset.itemId!==String(chosen.id))
    return toast("Odśwież dane zamówienia.",true);
  const itemId=chosen.id;
  const qty=Number(form.elements.quantity.value);
  const locationId=Number(form.elements.location_id.value);
  const remaining=chosen.order_status?.quantity||0;
  if(!Number.isSafeInteger(qty)||qty<1||qty>remaining||!locationId)
    return toast("Podaj lokalizację i ilość nie większą od zamówionej.",true);
  if(!confirm("Potwierdzasz fizyczne przyjęcie "+fmt(qty)+" szt. na stan magazynu?"))
    return;
  const body={location_id:locationId,quantity:qty};
  if(chosen.kind==="ecu"){
    body.product_state=form.elements.product_state.value;
    body.technical_state=form.elements.technical_state.value;
  }
  const button=form.querySelector('button[type="submit"]');
  button.disabled=true;
  try{
    const response=await api("/api/items/"+itemId+"/order-delivery",{
      method:"POST",body:JSON.stringify(body),
    });
    await Promise.all([loadItems(),loadStats(),loadLow()]);
    await openItem(itemId,"receive");
    toast("Przyjęto "+fmt(response.received)+" szt. "+(
      response.remaining_ordered?
        "Do odbioru pozostało "+fmt(response.remaining_ordered)+" szt.":
        "Zamówienie zakończone."));
  }catch(e){toast(e.message,true);}
  finally{button.disabled=false;}
}

async function savePurchaseStatus(event){
  event.preventDefault();
  const form=event.currentTarget;
  if(session?.role!=="admin"||!chosen||form.dataset.itemId!==String(chosen.id))return;
  const status=form.elements.status.value,ordered=status==="ordered";
  const quantity=ordered?Number(form.elements.quantity.value):0;
  if(ordered&&(!Number.isSafeInteger(quantity)||quantity<1||quantity>2_000_000_000))
    return toast("Nieprawidłowa ilość zamówiona.",true);
  const button=form.querySelector('[type="submit"]');button.disabled=true;
  try{
    await api("/api/items/"+chosen.id+"/order-status",{method:"PUT",
      body:JSON.stringify({status,quantity,note:ordered?form.elements.note.value:""})});
    toast(ordered?"Oznaczono produkt jako Zamówione.":"Usunięto status Zamówione.");
    await Promise.all([loadItems(),loadLow()]);
    const id=chosen.id,action=byId("operation-form").elements.action.value;
    await openItem(id,action);
  }catch(e){toast(e.message,true);}
  finally{button.disabled=false;}
}
function renderElectronicDetails(details){
  const isPart=details.kind==="part";
  byId("part-docs").hidden=!isPart;
  byId("part-edit-details").hidden=!isPart||session?.role!=="admin";
  if(isPart){
    const info=[
      ["Kategoria",details.category],["Obudowa",details.package],
      ["Parametry dodatkowe",details.parameters],
      ...Object.entries(electronicSpecLabels).map(([name,label])=>[label,details.specs?.[name]]),
    ];
    byId("detail-content").insertAdjacentHTML("beforeend",
      info.map(([label,value])=>detailLine(label,value)).join(""));
    renderElectronicDocs(details);
    if(session?.role==="admin"){
      const form=byId("part-edit-form");
      form.dataset.itemId=String(details.id);
      for(const key of ["designation","primary_number","manufacturer","category",
                        "package","parameters","notes"]){
        form.elements.namedItem(key).value=details[key]||"";
      }
      for(const key of Object.keys(electronicSpecLabels))
        form.elements.namedItem("spec_"+key).value=details.specs?.[key]||"";
    }
  }
  if(details.order_status?.status==="ordered"){
    byId("detail-content").insertAdjacentHTML("beforeend",
      detailLine("Status zakupu","Zamówione: "+fmt(details.order_status.quantity)+" szt."));
  }
  renderPurchaseStatus(details);
}
function renderElectronicDocs(details){
  const documents=details.documents||[];
  byId("part-doc-list").innerHTML=documents.length?
    documents.map(doc=>'<div class="doc-entry"><span class="doc-filename">'+
      esc(doc.filename)+'<small> · '+esc(electronicDocumentLabels[doc.doc_type]||doc.doc_type)+
      ' · '+fmt(doc.bytes)+' B</small></span>'+
      '<span class="doc-controls"><button type="button" class="small doc-preview" data-document-id="'+
        doc.id+'">Podgląd</button><a class="secondary doc-download" download href="/api/items/'+
      details.id+'/documents/'+doc.id+'">Pobierz</a>'+
      (session?.role==="admin"?'<button class="small danger remove-part-doc" type="button" data-document-id="'+
        doc.id+'">Usuń</button>':"")+'</span></div>').join(""):
    '<p class="muted">Brak dokumentacji. Możesz dołączyć kartę katalogową lub schemat.</p>';
  byId("part-doc-upload").dataset.itemId=String(details.id);
}
async function uploadDetailDocument(event){
  event.preventDefault();
  const form=event.currentTarget;
  if(!chosen||chosen.kind!=="part"||form.dataset.itemId!==String(chosen.id))return;
  const file=form.elements.document.files[0];
  if(!file)return toast("Wybierz plik.",true);
  const button=form.querySelector('[type="submit"]');button.disabled=true;
  try{
    await sendElectronicDocument(chosen.id,file,form.elements.doc_type.value);
    form.reset();
    const id=chosen.id,action=byId("operation-form").elements.action.value;
    await openItem(id,action);
    toast("Dodano dokumentację techniczną.");
  }catch(e){toast(e.message,true);}
  finally{button.disabled=false;}
}
async function saveElectronicsSpecs(event){
  event.preventDefault();
  const form=event.currentTarget;
  if(session?.role!=="admin"||!chosen||chosen.kind!=="part"||
     form.dataset.itemId!==String(chosen.id))return;
  const fields=Object.fromEntries(new FormData(form).entries());
  const specs={};
  for(const key of Object.keys(electronicSpecLabels))
    specs[key]=(fields["spec_"+key]||"").trim();
  const body={specs};
  for(const key of ["designation","primary_number","manufacturer","category","package","parameters","notes"])
    body[key]=(fields[key]||"").trim();
  if(!body.designation||!body.category)return toast("Wypełnij oznaczenie i kategorię.",true);
  const button=form.querySelector('[type="submit"]');button.disabled=true;
  try{
    await api("/api/items/"+chosen.id,{method:"PATCH",body:JSON.stringify(body)});
    const id=chosen.id,action=byId("operation-form").elements.action.value;
    await Promise.all([loadItems(),loadBrands()]);
    await openItem(id,action);
    toast("Zapisano parametry elementu.");
  }catch(e){toast(e.message,true);}
  finally{button.disabled=false;}
}
async function removeElectronicDocument(docId){
  if(session?.role!=="admin"||!chosen||chosen.kind!=="part")return;
  if(!confirm("Usunąć ten dokument techniczny?"))return;
  try{
    const id=chosen.id;
    await api("/api/items/"+id+"/documents/"+docId,{method:"DELETE",body:"{}"});
    const action=byId("operation-form").elements.action.value;
    await openItem(id,action);
    toast("Usunięto dokument.");
  }catch(e){toast(e.message,true);}
}
async function quickPurchaseStatus(id,mark){
  if(session?.role!=="admin")return;
  if(!confirm(mark?"Oznaczyć element jako Zamówione?":"Cofnąć status Zamówione?"))return;
  try{
    const row=mark?await api("/api/items/"+id+"/minimum"):null;
    const item=mark?await api("/api/items/"+id):null;
    const quantity=mark?Math.max(1,(row.minimum||0)-(item.total||0)):0;
    await api("/api/items/"+id+"/order-status",{method:"PUT",body:JSON.stringify({
      status:mark?"ordered":"none",quantity,note:"",
    })});
    toast(mark?"Status Zamówione zapisany.":"Status zamówienia cofnięty.");
    await Promise.all([loadLow(),loadItems()]);
  }catch(e){toast(e.message,true);}
}

/* Authenticated, short-lived document preview inside a second native modal.
   The original attachment endpoint and download workflow stay unchanged. */
let documentPreviewUrl=null;
let documentPreviewController=null;
let documentPreviewGeneration=0;
let documentPreviewZoom=1;

function cleanupDocumentPreview(){
  documentPreviewGeneration++;
  if(documentPreviewController){
    documentPreviewController.abort();
    documentPreviewController=null;
  }
  const frame=byId("doc-preview-pdf"),image=byId("doc-preview-image");
  frame.hidden=true;
  image.hidden=true;
  frame.removeAttribute("src");
  image.removeAttribute("src");
  if(documentPreviewUrl){
    URL.revokeObjectURL(documentPreviewUrl);
    documentPreviewUrl=null;
  }
  byId("doc-preview-image-tools").hidden=true;
  documentPreviewZoom=1;
}

function closeElectronicDocumentPreview(){
  const dialog=byId("document-preview-dialog");
  if(dialog.open)dialog.close();
  else cleanupDocumentPreview();
}

function updateDocumentPreviewZoom(next){
  if(!byId("document-preview-dialog").open||byId("doc-preview-image").hidden)return;
  documentPreviewZoom=Math.max(1,Math.min(4,next));
  byId("doc-preview-image").style.width=(100*documentPreviewZoom)+"%";
  byId("doc-zoom-label").textContent=Math.round(100*documentPreviewZoom)+"%";
  byId("doc-zoom-in").disabled=documentPreviewZoom>=4;
  byId("doc-zoom-out").disabled=documentPreviewZoom<=1;
}

async function openElectronicDocumentPreview(documentId){
  const item=chosen;
  if(!session||!item||item.kind!=="part"||!byId("detail-dialog").open)return;
  const doc=(item.documents||[]).find(row=>Number(row.id)===documentId);
  if(!doc){
    toast("Nie znaleziono tego dokumentu w produkcie.",true);
    return;
  }
  const mime=doc.mime;
  if(!["application/pdf","image/png","image/jpeg"].includes(mime)){
    toast("Podgląd nie obsługuje tego formatu. Użyj Pobierz.",true);
    return;
  }
  cleanupDocumentPreview();
  const generation=documentPreviewGeneration;
  const dialog=byId("document-preview-dialog");
  const status=byId("doc-preview-status");
  const pdf=byId("doc-preview-pdf");
  const image=byId("doc-preview-image");
  const url="/api/items/"+item.id+"/documents/"+doc.id;
  byId("doc-preview-title").textContent=mime==="application/pdf"?"Podgląd PDF":"Podgląd obrazu";
  byId("doc-preview-filename").textContent=doc.filename;
  byId("doc-preview-download").href=url;
  byId("doc-preview-download").download=doc.filename;
  status.hidden=false;
  status.textContent="Wczytywanie dokumentu…";
  byId("doc-preview-content").scrollTop=0;
  dialog.showModal();
  const controller=new AbortController();
  documentPreviewController=controller;
  try{
    const response=await fetch(url,{credentials:"same-origin",cache:"no-store",signal:controller.signal});
    if(!response.ok){
      if(response.status===401){
        showLogin();
        throw new Error("Sesja wygasła. Zaloguj się ponownie.");
      }
      throw new Error("Nie można pobrać dokumentu (HTTP "+response.status+").");
    }
    const receivedType=(response.headers.get("Content-Type")||"").split(";")[0].trim().toLowerCase();
    if(receivedType!==mime)
      throw new Error("Nieprawidłowy format pobranego dokumentu.");
    const contents=await response.blob();
    if(!contents.size||contents.size>8*1024*1024)
      throw new Error("Nieprawidłowy rozmiar pobranego dokumentu.");
    if(controller.signal.aborted||generation!==documentPreviewGeneration||!dialog.open)
      return;
    documentPreviewUrl=URL.createObjectURL(new Blob([contents],{type:mime}));
    if(mime==="application/pdf"){
      pdf.hidden=false;
      pdf.src=documentPreviewUrl;
      status.hidden=false;
      status.textContent="Jeśli przeglądarka nie wyświetla PDF, użyj „Pobierz plik” poniżej.";
    }else{
      image.alt="Podgląd: "+doc.filename;
      image.hidden=false;
      byId("doc-preview-image-tools").hidden=false;
      image.style.width="100%";
      image.src=documentPreviewUrl;
      updateDocumentPreviewZoom(1);
    }
  }catch(e){
    if(controller.signal.aborted||generation!==documentPreviewGeneration||!dialog.open)
      return;
    status.hidden=false;
    status.textContent="Nie udało się otworzyć podglądu. "+e.message+" Możesz pobrać plik.";
  }finally{
    if(documentPreviewController===controller)documentPreviewController=null;
  }
}

/* Defer keeps both scripts in the same global scope; handlers reuse auth & CSRF. */
document.addEventListener("DOMContentLoaded",()=>{
  byId("show-add-part").addEventListener("click",openPartDialog);
  byId("part-form").addEventListener("submit",savePart);
  byId("part-dialog").addEventListener("close",()=>{
    electronicRevision++;clearTimeout(electronicTimer);electronicCandidates=[];
  });
  byId("part-form").addEventListener("input",event=>{
    const field=event.target.name||"";
    if(["designation","primary_number","manufacturer","category","package","parameters",
        ...Object.keys(electronicSpecLabels).map(k=>"spec_"+k)].includes(field)){
      schedulePartSimilar();
    }
    if(field==="quantity"||field==="location_id")renderPartSimilar();
  });
  byId("part-allow-variant").addEventListener("change",renderPartSimilar);
  byId("part-order-on-create").addEventListener("change",event=>{
    byId("part-order-create-quantity-label").hidden=!event.target.checked;
  });
  byId("part-location-toggle").addEventListener("click",()=>{
    const panel=byId("part-location-panel");panel.hidden=!panel.hidden;
    if(!panel.hidden)byId("part-location-code").focus();
  });
  byId("part-location-save").addEventListener("click",savePartLocation);
  byId("part-doc-upload").addEventListener("submit",uploadDetailDocument);
  const preview=byId("document-preview-dialog");
  preview.addEventListener("close",cleanupDocumentPreview);
  byId("doc-preview-close").addEventListener("click",closeElectronicDocumentPreview);
  byId("doc-preview-dismiss").addEventListener("click",closeElectronicDocumentPreview);
  byId("detail-dialog").addEventListener("close",()=>{
    if(preview.open)closeElectronicDocumentPreview();
  });
  byId("doc-preview-image").addEventListener("load",()=>{
    if(preview.open&&!byId("doc-preview-image").hidden)
      byId("doc-preview-status").hidden=true;
  });
  byId("doc-preview-image").addEventListener("error",()=>{
    if(preview.open&&!byId("doc-preview-image").hidden){
      byId("doc-preview-status").hidden=false;
      byId("doc-preview-status").textContent=
        "Nie można wyświetlić tego obrazu. Pobierz plik, aby otworzyć go poza Magazynem.";
    }
  });
  byId("doc-zoom-in").addEventListener("click",()=>updateDocumentPreviewZoom(documentPreviewZoom+.5));
  byId("doc-zoom-out").addEventListener("click",()=>updateDocumentPreviewZoom(documentPreviewZoom-.5));
  byId("doc-zoom-fit").addEventListener("click",()=>updateDocumentPreviewZoom(1));
  byId("part-edit-form").addEventListener("submit",saveElectronicsSpecs);
  byId("order-status-form").addEventListener("submit",savePurchaseStatus);
  byId("order-delivery-form").addEventListener("submit",receiveOrderedDelivery);
  byId("order-status-form").elements.status.addEventListener("change",updatePurchaseInputs);
  document.addEventListener("click",event=>{
    const existing=event.target.closest(".select-existing-part");
    if(existing){
      byId("part-dialog").close();
      openItem(Number(existing.dataset.id),"receive");
      return;
    }
    const view=event.target.closest(".doc-preview");
    if(view){
      openElectronicDocumentPreview(Number(view.dataset.documentId));
      return;
    }
    const del=event.target.closest(".remove-part-doc");
    if(del){removeElectronicDocument(Number(del.dataset.documentId));return;}
    const mark=event.target.closest(".mark-ordered");
    if(mark){quickPurchaseStatus(Number(mark.dataset.id),true);return;}
    const clear=event.target.closest(".clear-ordered");
    if(clear){quickPurchaseStatus(Number(clear.dataset.id),false);}
  });
});
