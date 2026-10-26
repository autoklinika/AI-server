"use strict";
let session=null,locations=[],chosen=null,allItems=[];
const byId=(id)=>document.getElementById(id);
const esc=(s)=>String(s===null||s===undefined?"":s).replace(/[&<>"']/g,(c)=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const fmt=(n)=>new Intl.NumberFormat("pl-PL").format(n||0);
const stateLabels={new:"Nowy",used:"Używany",working:"Sprawny",faulty:"Uszkodzony",unknown:"Nieznany",na:"—"};
const reasonLabels={repair:"Naprawa klienta",sale:"Sprzedaż",workshop:"Potrzeby warsztatu",scrap:"Uszkodzenie / utylizacja",other:"Inne"};
const actionLabels={receive:"Przyjęcie",issue:"Wydanie",move:"Przesunięcie",adjust:"Korekta"};
let toastTimer;
function toast(msg,error=false){const n=byId("toast");n.textContent=msg;n.classList.toggle("error",error);n.hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>n.hidden=true,4200);}
async function api(path,opts={}){
  const options={credentials:"same-origin",...opts};
  options.headers={"Accept":"application/json",...(options.headers||{})};
  if(options.method && options.method!=="GET"){
    options.headers["Content-Type"]="application/json";
    if(session && session.csrf) options.headers["X-CSRF-Token"]=session.csrf;
  }
  const response=await fetch(path,options);
  let data;try{data=await response.json();}catch{data={detail:"Nieprawidłowa odpowiedź serwera"};}
  if(!response.ok){if(response.status===401 && !path.endsWith("/login")){showLogin();}
    throw new Error(typeof data.detail==="string"?data.detail:"Błąd żądania ("+response.status+")");}
  return data;
}
function showLogin(){
  resetTransfers();session=null;byId("app").hidden=true;byId("login").hidden=false;
}
function setSignedIn(user){
  session=user;byId("login").hidden=true;byId("app").hidden=false;
  byId("current-user").textContent=user.username+" · "+(user.role==="admin"?"Administrator":"Użytkownik");
  document.querySelectorAll(".admin-only").forEach((n)=>n.hidden=user.role!=="admin");
  showTab("products");
}
function showTab(tab){
  if(tab==="admin"&&(!session||session.role!=="admin"))return;
  document.querySelectorAll(".page").forEach((n)=>n.hidden=n.id!=="page-"+tab);
  document.querySelectorAll(".nav-item").forEach((n)=>n.classList.toggle("active",n.dataset.tab===tab));
  if(tab==="products") loadItems();
  if(tab==="low") loadLow();
  if(tab==="history") loadHistory();
  if(tab==="admin") loadAdmin();
}
function option(code,label){return '<option value="'+esc(code)+'">'+esc(label)+'</option>';}
function locationOptions(empty=false){
  return (empty?option("","Wszystkie lokalizacje"):"") + locations.map((r)=>option(r.id,r.code+(r.description?" — "+r.description:""))).join("");
}
async function loadLocations(){
  locations=await api("/api/locations");
  byId("inventory-location").innerHTML=locationOptions();
  clearInventory();
  byId("filter-location").innerHTML=locationOptions(true);
  byId("new-location").innerHTML=locationOptions();
  byId("operation-location").innerHTML=locationOptions();
  byId("operation-destination").innerHTML=locationOptions();
}
async function loadStats(){
  const s=await api("/api/stats");
  byId("stats").innerHTML='<div class="stat-card"><strong>'+fmt(s.items)+'</strong><span>Pozycji katalogowych</span></div>'+
    '<div class="stat-card"><strong>'+fmt(s.units)+'</strong><span>Sztuk łącznie</span></div>'+
    '<div class="stat-card"><strong>'+fmt(s.locations)+'</strong><span>Lokalizacji</span></div>';
}
async function loadItems(){
  if(!session)return;
  try{
    const params=new URLSearchParams();
    const filters={"q":"search","kind":"filter-kind","brand":"filter-brand",
      "product_state":"filter-product-state","technical_state":"filter-tech-state",
      "location_id":"filter-location"};
    for(const [key,id] of Object.entries(filters)){
      const v=byId(id).value.trim();if(v)params.set(key,v);
    }
    params.set("limit","500");
    const items=await api("/api/items?"+params.toString());
    const list=byId("products");
    list.innerHTML="";
    if(!items.length){list.innerHTML='<div class="panel empty">Nie znaleziono produktów.</div>';return;}
    for(const item of items){
      const row=document.createElement("article");row.className="result-card";
      const sub=[item.manufacturer,item.model,item.primary_number,item.brand].filter(Boolean).join(" · ");
      row.innerHTML='<div><div class="result-title">'+esc(item.designation)+'</div>'+
        '<div class="result-sub">'+esc(sub)+'</div>'+
        '<span class="pill">'+(item.kind==="ecu"?"Sterownik":"Elektronika")+'</span></div>'+
        '<div><div class="result-total">'+fmt(item.total)+' szt.</div>'+
        '<button class="small open-item" data-id="'+item.id+'">Szczegóły</button></div>';
      list.append(row);
    }
  }catch(e){toast(e.message,true);}
}
async function loadBrands(){
  try{
    allItems=await api("/api/items?limit=500");
    const used=new Set();
    for(const item of allItems)for(const brand of item.brands||[])used.add(brand);
    const old=byId("filter-brand").value;
    const brands=Array.from(used).sort((a,b)=>a.localeCompare(b,"pl"));
    byId("filter-brand").innerHTML=option("","Wszystkie marki")+brands.map(b=>option(b,b)).join("");
    if(brands.includes(old))byId("filter-brand").value=old;
  }catch(e){toast(e.message,true);}
}
async function openItem(id){
  try{
    chosen=await api("/api/items/"+id);
    byId("detail-title").textContent=chosen.designation;
    byId("detail-kind").textContent=chosen.kind==="ecu"?"Sterownik · "+chosen.brand:"Elektronika";
    const lines=[
      ["Producent",chosen.manufacturer],["Typ / model",chosen.model],
      ["Numer główny",chosen.primary_number],["Numery dodatkowe",(chosen.numbers||[]).map(n=>n.number).join(", ")],
      ["Marki",(chosen.brands||[]).join(", ")],["HW / SW",[chosen.hw,chosen.sw].filter(Boolean).join(" / ")],
      ["Obudowa / parametry",[chosen.package,chosen.parameters].filter(Boolean).join(" / ")],
      ["Ilość łączna",fmt(chosen.total)+" szt."]];
    const rowHtml=lines.filter(x=>x[1]).map(x=>'<div class="detail-line"><strong>'+esc(x[0])+':</strong> '+esc(x[1])+'</div>').join("");
    const stockHtml=chosen.balances.length?chosen.balances.map(b=>
      '<div class="detail-line">'+esc(b.location)+': '+fmt(b.quantity)+' szt. — '+
      esc(stateLabels[b.product_state]||b.product_state)+' / '+esc(stateLabels[b.technical_state]||b.technical_state)+'</div>').join("")
      :'<div class="detail-line">Brak sztuk w magazynie.</div>';
    byId("detail-content").innerHTML=rowHtml+'<h3>Rozmieszczenie</h3>'+stockHtml;
    byId("operation-item-id").value=chosen.id;
    document.querySelectorAll(".ecu-operation").forEach(n=>n.hidden=chosen.kind!=="ecu");
    byId("operation-action").value="receive";
    byId("operation-form").reset();
    byId("operation-item-id").value=chosen.id;
    if(chosen.balances.length)byId("operation-location").value=String(chosen.balances[0].location_id);
    byId("detail-admin").hidden=session.role!=="admin";
    byId("delete-item").dataset.id=String(chosen.id);
    updateOperation();
    byId("detail-dialog").showModal();
  }catch(e){toast(e.message,true);}
}
function updateOperation(){
  const form=byId("operation-form");
  const action=form.elements.action.value;
  byId("reason-wrapper").hidden=action!=="issue";
  byId("order-wrapper").hidden=action!=="issue"||form.elements.reason.value!=="repair";
  byId("destination-wrapper").hidden=action!=="move";
  form.elements.quantity.min=action==="adjust"?"0":"1";
  const loc=Number(form.elements.location_id.value);
  const ps=chosen&&chosen.kind==="ecu"?form.elements.product_state.value:"na";
  const ts=chosen&&chosen.kind==="ecu"?form.elements.technical_state.value:"na";
  const row=chosen?.balances.find(b=>b.location_id===loc&&b.product_state===ps&&b.technical_state===ts);
  const before=row?row.quantity:0;
  const qty=Math.max(0,Number(form.elements.quantity.value)||0);
  const after=action==="receive"?before+qty:action==="adjust"?qty:before-qty;
  const okay=after>=0&&(action!=="move"||form.elements.to_location_id.value!==form.elements.location_id.value);
  byId("operation-preview").textContent="Wybrany stan: "+before+" szt. → "+after+
    " szt. "+(!okay?"— niewystarczający stan lub nieprawidłowa lokalizacja":"");
  byId("operation-submit").disabled=!okay;
}
async function submitOperation(ev){
  ev.preventDefault();
  const f=ev.currentTarget;
  const data=Object.fromEntries(new FormData(f).entries());
  for(const k of ["item_id","location_id","to_location_id","quantity"]){
    if(data[k]!=="")data[k]=Number(data[k]);else data[k]=null;
  }
  if(chosen.kind!=="ecu"){data.product_state="na";data.technical_state="na";}
  try{
    await api("/api/stock",{method:"POST",body:JSON.stringify(data)});
    byId("detail-dialog").close();toast("Zapisano operację magazynową");
    await Promise.all([loadStats(),loadItems()]);
  }catch(e){toast(e.message,true);}
}
function splitNumbers(s){return String(s||"").split(/[\n,;]+/).map(x=>x.trim()).filter(Boolean);}
function setCreateKind(){
  const ecu=byId("new-kind").value==="ecu";
  document.querySelectorAll("#item-dialog .ecu-field").forEach(n=>n.hidden=!ecu);
  byId("new-brand").required=ecu;
}
async function submitItem(ev){
  ev.preventDefault();
  const f=ev.currentTarget;
  const values=Object.fromEntries(new FormData(f).entries());
  const n=Number(values.quantity);const locationId=Number(values.location_id);
  if(!locationId){toast("Najpierw administrator musi dodać lokalizację.",true);return;}
  const data={...values,brands:splitNumbers(values.brands),
    numbers:splitNumbers(values.numbers).map(x=>({number:x,number_type:"other"}))};
  delete data.quantity;delete data.location_id;delete data.product_state;delete data.technical_state;
  if(data.kind==="part")data.brand="";
  let created;
  try{
    created=await api("/api/items",{method:"POST",body:JSON.stringify(data)});
    if(n>0){
      await api("/api/stock",{method:"POST",body:JSON.stringify({
        action:"receive",item_id:created.id,location_id:locationId,quantity:n,
        product_state:values.kind==="ecu"?values.product_state:"na",
        technical_state:values.kind==="ecu"?values.technical_state:"na"})});
    }
    byId("item-dialog").close();f.reset();toast("Produkt został dodany");
    await Promise.all([loadItems(),loadBrands(),loadStats()]);
  }catch(e){
    toast((created?"Produkt utworzono (ID "+created.id+"), ale przyjęcie wymaga sprawdzenia: ":"")+e.message,true);
  }
}
async function loadLow(){
  try{
    const rows=await api("/api/low-stock");
    byId("low-results").innerHTML=rows.length?rows.map(r=>
      '<article class="result-card"><div><strong>'+esc(r.designation)+'</strong><div class="result-sub">'+esc(r.brand)+'</div></div>'+
      '<div class="result-total">'+fmt(r.total)+' / '+fmt(r.minimum)+' szt.<div>'+
      '<button class="small open-item" data-id="'+r.item_id+'">Szczegóły</button></div></div></article>').join("")
      :'<div class="panel empty">Brak produktów poniżej progu.</div>';
  }catch(e){toast(e.message,true);}
}
async function loadHistory(){
  try{
    const rows=await api("/api/history?limit=200");
    const body=rows.map(x=>
      '<tr><td>'+esc((x.created_at||"").replace("T"," "))+'</td>'+
      '<td>'+esc(x.actor_name)+'</td><td>'+esc(actionLabels[x.action]||x.action)+'</td>'+
      '<td>'+esc(x.item_label)+'</td><td>'+fmt(x.quantity)+' szt.</td>'+
      '<td>'+esc(x.location_code+(x.to_location_code?" → "+x.to_location_code:""))+'</td>'+
      '<td>'+esc(reasonLabels[x.reason]||x.reason||"")+'</td>'+
      '<td>'+(session.role==="admin"?'<button class="small danger delete-history" data-id="'+x.id+'">Usuń</button>':"")+'</td></tr>').join("");
    byId("history-results").innerHTML=rows.length?'<div class="table-wrap"><table class="history-table"><thead>'+
      '<tr><th>Czas (UTC)</th><th>Użytkownik</th><th>Operacja</th><th>Produkt</th><th>Ilość</th>'+
      '<th>Lokalizacja</th><th>Powód</th><th></th></tr></thead><tbody>'+body+'</tbody></table></div>'
      :'<div class="empty">Brak operacji.</div>';
  }catch(e){toast(e.message,true);}
}
async function loadAdmin(){
  if(session.role!=="admin")return;
  try{
    const users=await api("/api/users");
    byId("users-list").innerHTML=users.map(x=>
      '<div class="list-row"><strong>'+esc(x.username)+'</strong> · '+(x.role==="admin"?"Administrator":"Użytkownik")+
      ' · '+(x.active?"aktywny":"nieaktywny")+' <button class="small toggle-user" data-id="'+x.id+
      '" data-active="'+x.active+'">'+(x.active?"Zablokuj":"Aktywuj")+'</button></div>').join("");
    byId("locations-list").innerHTML=locations.map(x=>
      '<div class="list-row"><strong>'+esc(x.code)+'</strong> '+esc(x.description)+'</div>').join("");
  }catch(e){toast(e.message,true);}
}
async function formUser(ev){
  ev.preventDefault();
  const obj=Object.fromEntries(new FormData(ev.currentTarget).entries());
  try{await api("/api/users",{method:"POST",body:JSON.stringify(obj)});
    ev.currentTarget.reset();toast("Dodano użytkownika");loadAdmin();}
  catch(e){toast(e.message,true);}
}
async function formLocation(ev){
  ev.preventDefault();
  const obj=Object.fromEntries(new FormData(ev.currentTarget).entries());
  try{await api("/api/locations",{method:"POST",body:JSON.stringify(obj)});
    ev.currentTarget.reset();await loadLocations();loadAdmin();toast("Dodano lokalizację");}
  catch(e){toast(e.message,true);}
}
async function formMinimum(ev){
  ev.preventDefault();
  if(!chosen)return;
  const n=Number(new FormData(ev.currentTarget).get("minimum"));
  try{await api("/api/items/"+chosen.id+"/minimum",{method:"PUT",body:JSON.stringify({minimum:n})});
    toast("Zapisano stan minimalny");}catch(e){toast(e.message,true);}
}
document.addEventListener("DOMContentLoaded",async()=>{
  byId("login-form").addEventListener("submit",async(ev)=>{
    ev.preventDefault();
    const obj=Object.fromEntries(new FormData(ev.currentTarget).entries());
    try{const user=await api("/api/auth/login",{method:"POST",body:JSON.stringify(obj)});
      setSignedIn(user);await Promise.all([loadLocations(),loadBrands(),loadStats(),loadItems()]);}
    catch(e){toast(e.message,true);}
  });
  byId("logout").addEventListener("click",async()=>{
    try{await api("/api/auth/logout",{method:"POST",body:"{}"});}catch{}
    showLogin();
  });
  document.querySelectorAll(".nav-item").forEach(n=>n.addEventListener("click",()=>showTab(n.dataset.tab)));
  byId("show-add").addEventListener("click",()=>{
    if(!locations.length){toast("Administrator musi najpierw dodać lokalizację.",true);return;}
    setCreateKind();byId("item-dialog").showModal();
  });
  document.querySelectorAll(".close-dialog").forEach(n=>n.addEventListener("click",()=>n.closest("dialog").close()));
  byId("new-kind").addEventListener("change",setCreateKind);
  byId("item-form").addEventListener("submit",submitItem);
  byId("operation-form").addEventListener("submit",submitOperation);
  byId("operation-form").addEventListener("input",updateOperation);
  byId("operation-form").addEventListener("change",updateOperation);
  byId("user-form").addEventListener("submit",formUser);
  byId("location-form").addEventListener("submit",formLocation);
  byId("minimum-form").addEventListener("submit",formMinimum);
  for(const id of ["search","filter-kind","filter-brand","filter-product-state","filter-tech-state","filter-location"]){
    byId(id).addEventListener(id==="search"?"input":"change",loadItems);
  }
  document.addEventListener("click",async(ev)=>{
    const target=ev.target.closest("[data-id]");
    if(!target||!session)return;
    const id=Number(target.dataset.id);
    if(target.classList.contains("open-item"))openItem(id);
    if(target.classList.contains("toggle-user")){
      if(!confirm("Zmienić status konta?"))return;
      try{await api("/api/users/"+id,{method:"PATCH",body:JSON.stringify({active:target.dataset.active!=="1"})});
        toast("Zmieniono status konta");loadAdmin();}
      catch(e){toast(e.message,true);}
    }
    if(target.classList.contains("delete-history")){
      if(!confirm("Usunąć wpis historii? Administrator ma taką możliwość."))return;
      try{await api("/api/history/"+id,{method:"DELETE",body:"{}"});toast("Usunięto wpis");loadHistory();}
      catch(e){toast(e.message,true);}
    }
  });
  byId("delete-item").addEventListener("click",async()=>{
    if(!chosen||!confirm("Trwale usunąć pozycję i jej stany?"))return;
    try{await api("/api/items/"+chosen.id,{method:"DELETE",body:"{}"});
      byId("detail-dialog").close();toast("Usunięto produkt");
      await Promise.all([loadItems(),loadStats()]);}
    catch(e){toast(e.message,true);}
  });
  try{const me=await api("/api/auth/me");
    setSignedIn(me);await Promise.all([loadLocations(),loadBrands(),loadStats(),loadItems()]);}
  catch{showLogin();}
});

let inventoryRows=[],inventoryLocation=null,inventoryRequest=0,importUpload=null;
function clearInventory(){
  inventoryRequest++;inventoryRows=[];inventoryLocation=null;
  byId("inventory-results").replaceChildren();byId("inventory-apply").disabled=true;
}
function clearImport(){
  importUpload=null;byId("import-apply").disabled=true;byId("import-results").replaceChildren();
}
function resetTransfers(){clearInventory();clearImport();byId("import-file").value="";}
async function loadInventory(){
  clearInventory();
  const request=inventoryRequest,loc=Number(byId("inventory-location").value),user=session;
  if(!loc){toast("Wybierz lokalizację",true);return;}
  try{
    const rows=await api("/api/inventory?location_id="+loc);
    if(request!==inventoryRequest||user!==session)return;
    inventoryRows=rows;inventoryLocation=loc;
    byId("inventory-results").innerHTML='<table><thead><tr><th>Produkt</th><th>Stan</th><th>Sprawność</th><th>Oczekiwane</th><th>Policzone</th><th>Różnica</th></tr></thead><tbody>'+rows.map((r,i)=>
      '<tr><td>'+esc(r.designation)+' (#'+r.item_id+')</td><td>'+esc(stateLabels[r.product_state])+'</td><td>'+esc(stateLabels[r.technical_state])+'</td><td>'+fmt(r.expected_quantity)+'</td><td><input aria-label="Policzone: '+esc(r.designation)+'" class="inventory-count" data-index="'+i+'" type="number" min="0" max="2000000000" step="1" placeholder="Bez zmian" '+(session.role==='admin'?'':'disabled')+'></td><td class="inventory-delta">—</td></tr>').join('')+'</tbody></table>';
    byId("inventory-apply").disabled=!rows.length;
  }catch(e){toast(e.message,true);}
}
async function downloadTable(path,filename){
  try{
    const response=await fetch(path,{credentials:"same-origin"});
    if(!response.ok){const error=await response.json();throw new Error(error.detail);}
    const url=URL.createObjectURL(await response.blob()),a=document.createElement("a");
    a.href=url;a.download=filename;document.body.append(a);a.click();a.remove();
    setTimeout(()=>URL.revokeObjectURL(url),1000);
  }catch(e){toast(e.message,true);}
}
document.addEventListener("DOMContentLoaded",()=>{
  byId("inventory-load").addEventListener("click",loadInventory);
  byId("inventory-location").addEventListener("change",clearInventory);
  byId("inventory-results").addEventListener("input",ev=>{
    const input=ev.target;if(!input.classList.contains("inventory-count"))return;
    input.closest("tr").querySelector(".inventory-delta").textContent=input.value===""?'—':String(Number(input.value)-inventoryRows[Number(input.dataset.index)].expected_quantity);
  });
  byId("inventory-form").addEventListener("submit",async ev=>{
    ev.preventDefault();const rows=[];
    document.querySelectorAll(".inventory-count").forEach(input=>{
      if(input.value!==""){
        const {designation,...row}=inventoryRows[Number(input.dataset.index)];
        rows.push({...row,quantity:Number(input.value)});
      }
    });
    if(!rows.length||rows.length>1000){toast("Wypełnij od 1 do 1000 wierszy",true);return;}
    if(!confirm("Zastosować korekty dla "+rows.length+" pozycji stanów?"))return;
    byId("inventory-apply").disabled=true;
    try{await api("/api/inventory",{method:"POST",body:JSON.stringify({location_id:inventoryLocation,rows})});
      toast("Zapisano inwentaryzację");await loadInventory();loadStats();}
    catch(e){toast(e.message,true);byId("inventory-apply").disabled=false;}
  });
  for(const format of ["csv","xlsx"]){
    byId("export-"+format).addEventListener("click",()=>{
      const query=new URLSearchParams({format});
      if(byId("export-kind").value)query.set("kind",byId("export-kind").value);
      if(byId("export-brand").value.trim())query.set("brand",byId("export-brand").value.trim());
      downloadTable("/api/export?"+query,"magazyn-snapshot."+format);
    });
    byId("template-"+format).addEventListener("click",()=>downloadTable("/api/import/template?format="+format,"magazyn-new."+format));
  }
  byId("import-file").addEventListener("change",clearImport);
  byId("import-preview").addEventListener("click",async()=>{
    clearImport();const file=byId("import-file").files[0],user=session;
    if(!file||file.size>1000000){toast("Wybierz plik do 1 MB",true);return;}
    const format=file.name.split('.').pop().toLowerCase();
    if(!['csv','xlsx'].includes(format)){toast("Wybierz CSV lub XLSX",true);return;}
    byId("import-preview").disabled=true;
    try{
      const bytes=new Uint8Array(await file.arrayBuffer());let binary='';
      for(const byte of bytes)binary+=String.fromCharCode(byte);
      const upload={format,content_base64:btoa(binary)};
      const result=await api("/api/import/preview",{method:"POST",body:JSON.stringify(upload)});
      if(file!==byId("import-file").files[0]||session!==user)return;
      byId("import-results").textContent='Pozycje: '+result.count+'. Poprawne: '+result.valid_count+'. Problemy: '+result.problems.length+'.';
      for(const problem of result.problems){const p=document.createElement('p');p.textContent='Wiersz '+problem.row+': '+problem.detail;byId("import-results").append(p);}
      if(result.token){importUpload={...upload,token:result.token};byId("import-apply").disabled=false;}
    }catch(e){toast(e.message,true);}finally{byId("import-preview").disabled=false;}
  });
  byId("import-apply").addEventListener("click",async()=>{
    if(!importUpload)return;
    const upload=importUpload;byId("import-apply").disabled=true;
    try{const result=await api("/api/import/apply",{method:"POST",body:JSON.stringify(upload)});
      clearImport();byId("import-results").textContent='Zaimportowano '+result.count+' nowych pozycji.';
      byId("import-file").value='';loadStats();loadItems();loadBrands();clearInventory();}
    catch(e){clearImport();toast(e.message+' Wykonaj podgląd ponownie.',true);}
  });
});
