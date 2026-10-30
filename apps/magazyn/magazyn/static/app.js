"use strict";

/* Magazyn UI V2 — no external JS libraries, all HTML from inventory is escaped. */
let session=null, locations=[], chosen=null, allItems=[], usersCache=[], linkedAccounts=[];
let searchRevision=0, itemRevision=0, similarRevision=0, similarTimer=null, toastTimer=null;
let similarCandidates=[], inventoryRows=[], inventoryLocation=null, inventoryRequest=0, importUpload=null;
let historyRows=[], backupArchiveRows=[];


const byId=id=>document.getElementById(id);
const esc=value=>String(value===null||value===undefined?"":value)
  .replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const fmt=value=>new Intl.NumberFormat("pl-PL").format(value||0);
const icon=name=>'<svg class="icon" aria-hidden="true"><use href="#i-'+name+'"></use></svg>';
const stateLabels={new:"Nowy",used:"Używany",working:"Sprawny",faulty:"Uszkodzony",unknown:"Nieznany",na:"—"};
const reasonLabels={repair:"Naprawa klienta",sale:"Sprzedaż",workshop:"Potrzeby warsztatu",scrap:"Uszkodzenie / utylizacja",other:"Inne"};
const actionLabels={receive:"Przyjęcie",issue:"Wydanie",move:"Przesunięcie",adjust:"Korekta"};
const pageNames={products:"Produkty",suppliers:"Hurtownie",low:"Do zamówienia",inventory:"Inwentaryzacja",history:"Historia",admin:"Ustawienia"};

function toast(message,isError=false){
  const target=byId("toast");
  target.textContent=message;
  target.classList.toggle("error",isError);
  target.hidden=false;
  clearTimeout(toastTimer);
  toastTimer=setTimeout(()=>{target.hidden=true;},5200);
}
function option(code,label){return '<option value="'+esc(code)+'">'+esc(label)+'</option>';}
function parseError(data,status){
  if(typeof data?.detail==="string")return data.detail;
  if(Array.isArray(data?.detail))return data.detail.map(x=>x.msg||"Błąd danych").join(", ");
  return "Żądanie nie powiodło się (HTTP "+status+")";
}
async function api(path,options={}){
  const settings={credentials:"same-origin",...options};
  settings.headers={"Accept":"application/json",...(settings.headers||{})};
  if(settings.method && settings.method.toUpperCase()!=="GET"){
    settings.headers["Content-Type"]="application/json";
    if(session?.csrf)settings.headers["X-CSRF-Token"]=session.csrf;
  }
  const result=await fetch(path,settings);
  let data;
  try{data=await result.json();}catch{data={detail:"Serwer zwrócił niepoprawną odpowiedź"};}
  if(!result.ok){
    if(result.status===401 && !path.endsWith("/login"))showLogin();
    throw new Error(parseError(data,result.status));
  }
  return data;
}
function resetTransfers(){clearInventory();clearImport();const f=byId("import-file");if(f)f.value="";}
function showLogin(){
  searchRevision++;itemRevision++;similarRevision++;
  resetTransfers();
  if(typeof resetSupplierUi==="function")resetSupplierUi();
  session=null;chosen=null;
  if(typeof resetFolderView==="function")resetFolderView();
  if(typeof resetSupplierComparison==="function")resetSupplierComparison();
  document.querySelectorAll("dialog[open]").forEach(dialog=>dialog.close());
  // Shared phones must not retain the previous employee's login or password.
  byId("login-form").reset();
  byId("user-form").reset();
  byId("app").hidden=true;byId("login").hidden=false;
  const result=byId("pairing-result");result.hidden=true;result.textContent="";
}
function setSignedIn(user){
  session=user;
  byId("login").hidden=true;byId("app").hidden=false;
  byId("current-user").textContent=user.username;
  byId("user-avatar").textContent=(user.username[0]||"M").toUpperCase();
  document.querySelectorAll(".admin-only").forEach(node=>{node.hidden=user.role!=="admin";});
  showTab("products");
}
function showTab(tab){
  if(!session || !(tab in pageNames))return;
  if(tab==="admin"&&session.role!=="admin")return;
  document.querySelectorAll(".page").forEach(el=>{el.hidden=el.id!=="page-"+tab;});
  document.querySelectorAll(".nav-item").forEach(el=>{
    const active=el.dataset.tab===tab;
    el.classList.toggle("active",active);
    if(active)el.setAttribute("aria-current","page");else el.removeAttribute("aria-current");
  });
  byId("current-section").textContent=pageNames[tab];
  const secret=byId("pairing-result");
  if(tab!=="admin"){secret.textContent="";secret.hidden=true;}
  if(tab==="products")loadItems();
  else if(tab==="low")loadLow();
  else if(tab==="history")loadHistory();
  else if(tab==="admin"){loadAdmin();loadFolders();loadBackupStatus();loadBackupArchives();loadMessagingUi();loadSupplierSettings();}
  // Switching top-level pages should be immediate. Smooth scrolling could
  // leave settings shortcuts temporarily behind the sticky mobile header.
  if(window.scrollY>0)window.scrollTo({top:0,behavior:"instant"});
}
function locationOptions(empty=false){
  if(!locations.length)return option("","Brak lokalizacji — utwórz pierwszą");
  return (empty?option("","Wszystkie lokalizacje"):"") +
    locations.map(r=>option(r.id,r.code+(r.description?" — "+r.description:""))).join("");
}
function setOptions(id,html,preserve=true){
  const select=byId(id),old=select.value;
  select.innerHTML=html;
  if(preserve&&[...select.options].some(o=>o.value===old))select.value=old;
}
async function loadLocations(){
  locations=await api("/api/locations");
  setOptions("filter-location",locationOptions(true));
  setOptions("inventory-location",locationOptions());
  setOptions("new-location",locationOptions());
  setOptions("part-location",locationOptions());
  setOptions("operation-location",locationOptions());
  setOptions("operation-destination",locationOptions());
  clearInventory();
}
async function loadStats(){
  if(!session)return;
  try{
    const [stats,low]=await Promise.all([api("/api/stats"),api("/api/low-stock")]);
    if(!session)return;
    const counter=byId("low-nav-count");
    counter.textContent=fmt(low.length);counter.hidden=low.length===0;
    const cards=[
      {label:"Pozycji",number:stats.items,caption:"w katalogu",icon:"box"},
      {label:"Sztuk łącznie",number:stats.units,caption:"na stanie",icon:"grid"},
      {label:"Lokalizacji",number:stats.locations,caption:"miejsc składowania",icon:"location"},
      {label:"Do zamówienia",number:low.length,caption:"wymaga uwagi",icon:"bell",attention:low.length>0},
    ];
    byId("stats").innerHTML=cards.map(s=>
      '<article class="stat-card'+(s.attention?' attention':'')+'">'+
      '<div class="stat-top"><span>'+esc(s.label)+'</span><span class="stat-icon">'+icon(s.icon)+'</span></div>'+
      '<strong>'+fmt(s.number)+'</strong><span class="stat-caption">'+esc(s.caption)+'</span></article>').join("");
  }catch(e){toast(e.message,true);}
}
async function loadBrands(){
  if(!session)return;
  try{
    allItems=await api("/api/items?limit=500");
    const used=[...new Set(allItems.flatMap(item=>item.brands||[]))].sort((a,b)=>a.localeCompare(b,"pl"));
    setOptions("filter-brand",option("","Wszystkie marki")+used.map(b=>option(b,b)).join(""));
  }catch(e){toast(e.message,true);}
}
function activeFilters(){
  const params=new URLSearchParams();
  for(const [key,id] of Object.entries({
    q:"search",kind:"filter-kind",brand:"filter-brand",
    product_state:"filter-product-state",technical_state:"filter-tech-state",
    location_id:"filter-location",
  })){
    const value=byId(id).value.trim();
    if(value)params.set(key,value);
  }
  params.set("limit","500");
  return params;
}
function updateKindButtons(kind){
  for(const button of document.querySelectorAll(".kind-choice")){
    const current=button.dataset.kind===kind;
    button.classList.toggle("active",current);
    button.setAttribute("aria-pressed",String(current));
  }
}
async function loadItems(){
  if(!session)return;
  const revision=++searchRevision;
  try{
    const filters=activeFilters();
    const results=await api("/api/items?"+filters.toString());
    if(revision!==searchRevision||!session)return;
    byId("results-count").textContent=fmt(results.length)+" "+(results.length===1?"wynik":results.length<5&&results.length>1?"wyniki":"wyników");
    const container=byId("products");
    container.replaceChildren();
    const view=prepareCatalogView(results,filters);
    const visible=view.items;
    const count=["home","root"].includes(folderView.mode)&&!view.grouped?results.length:visible.length;
    byId("results-count").textContent=fmt(count)+" "+(count===1?"produkt":count<5&&count>1?"produkty":"produktów");
    if(!visible.length){
      if(view.tiles){return;}
      const anyFilters=[...filters.entries()].some(([k,v])=>k!=="limit"&&!!v);
      const emptyFolder=!filters.get("q")&&["folder","unassigned"].includes(folderView.mode);
      const emptyTitle=emptyFolder?"Ten katalog jest pusty":
          (anyFilters?"Nie znaleziono pasujących produktów":"Magazyn jest jeszcze pusty");
      const emptyMessage=emptyFolder?
          "Dodaj produkt do tego katalogu lub wybierz inny katalog z drzewa.":
          (anyFilters?"Spróbuj innego numeru lub wyczyść filtry.":
          "Dodaj pierwszy sterownik lub element elektroniczny. Produkty pojawią się tutaj.");
      container.innerHTML='<div class="empty"><div class="empty-mark">'+icon("search")+'</div>'+
        '<h3>'+emptyTitle+'</h3><p>'+emptyMessage+'</p>'+
        (emptyFolder?"":anyFilters?'<button class="secondary" data-ui="clear-filters">Wyczyść filtry</button>':
          '<button class="primary" data-ui="add-first">'+icon("plus")+' Dodaj pierwszy produkt</button>')+
        '</div>';
      return;
    }
    const filtered=Boolean(filters.get("product_state")||filters.get("technical_state")||filters.get("location_id"));
    let previousGroup="";
    for(const item of visible){
      if(view.grouped){
        const group=folderGroupName(item);
        if(group!==previousGroup){
          const heading=document.createElement("h3");
          heading.className="folder-result-heading";
          heading.textContent=group;
          container.append(heading);
          previousGroup=group;
        }
      }
      const displayed=filtered?item.filtered_total:item.total;
      const extra=[item.primary_number,item.model,item.manufacturer,item.brand].filter(Boolean);
      const unique=[...new Set(extra)];
      const pills=[item.kind==="ecu"?"Sterownik":"Elektronika"];
      if(item.brand&&item.kind==="ecu")pills.push(item.brand);
      if(item.order_status==="ordered")pills.push("Zamówione: "+fmt(item.ordered_quantity)+" szt.");
      const row=document.createElement("article");row.className="result-card";
      row.innerHTML=
        '<div class="product-core"><span class="product-glyph '+(item.kind==="part"?"electronics":"")+'">'+
          icon(item.kind==="ecu"?"truck":"cpu")+'</span>'+
          '<div class="product-text"><strong class="product-title">'+esc(item.designation)+'</strong>'+
          '<div class="product-sub">'+unique.map(v=>'<span>'+esc(v)+'</span>').join('<span aria-hidden="true">·</span>')+'</div>'+
          '<div class="product-pills">'+pills.map((p,i)=>
             '<span class="pill'+(i>0?" secondary-pill":"")+'">'+esc(p)+'</span>').join("")+'</div></div></div>'+
        '<div class="product-aside"><div class="result-total">'+fmt(displayed)+' <span>szt.</span></div>'+
          (filtered&&displayed!==item.total?'<span class="subtle-note">Łącznie '+fmt(item.total)+' szt.</span>':"")+
          '<div class="product-actions"><button type="button" class="small open-item" data-id="'+item.id+'">Szczegóły '+icon("arrow")+'</button>'+
          '<button type="button" class="small quick-receive" data-id="'+item.id+'" title="Przyjmij sztuki">+ Przyjmij</button>'+
          '<button type="button" class="small quick-issue" data-id="'+item.id+'" title="Wydaj sztuki">− Wydaj</button></div></div>';
      container.append(row);
    }
  }catch(e){if(revision===searchRevision)toast(e.message,true);}
}
function resetAllFilters(){
  for(const id of ["search","filter-kind","filter-brand","filter-product-state","filter-tech-state","filter-location"])
    byId(id).value="";
  updateKindButtons("");
  resetFolderView();
  loadItems();
}
async function loadLow(){
  if(!session)return;
  try{
    const rows=await api("/api/low-stock");
    const result=byId("low-results");
    if(!rows.length){
      result.innerHTML='<div class="empty"><span class="empty-mark">'+icon("check")+'</span>'+
        '<h3>Wszystko pod kontrolą</h3><p>Żaden produkt nie osiągnął ustalonego minimum. Ustawisz je w szczegółach produktu.</p></div>';
      return;
    }
    result.innerHTML=rows.map(row=>
      '<article class="result-card"><div class="product-core">'+
        '<span class="product-glyph">'+icon("bell")+'</span>'+
        '<div class="product-text"><strong class="product-title">'+esc(row.designation)+'</strong>'+
        '<div class="product-sub">'+esc(row.brand||"Elektronika")+'</div>'+
        '<div class="product-pills"><span class="pill warning-pill">Osiągnięto minimum</span>'+
        (row.order_status==="ordered"?'<span class="pill">Zamówione: '+fmt(row.ordered_quantity)+' szt.</span>':"")+
        (row.recipient_user_id?'<span class="pill secondary-pill">Alert: '+esc(row.provider)+'</span>':"")+'</div></div></div>'+
        '<div class="product-aside"><div class="result-total">'+fmt(row.total)+' <span>/ '+fmt(row.minimum)+' szt.</span></div>'+
        '<div class="action-row"><button type="button" class="small open-item" data-id="'+row.item_id+'">Szczegóły '+icon("arrow")+'</button>'+
        (session.role==="admin"?
           (row.order_status==="ordered"?
             '<button type="button" class="small clear-ordered" data-id="'+row.item_id+'">Cofnij Zamówione</button>':
             '<button type="button" class="small mark-ordered" data-id="'+row.item_id+'">Oznacz Zamówione</button>'):"")+
        '</div></div></article>').join("");
  }catch(e){toast(e.message,true);}
}
async function loadHistory(){
  if(!session)return;
  try{
    const params=new URLSearchParams({limit:"200"});
    for(const [field,key] of [["history-query","q"],["history-actor","actor_id"],
                               ["history-from","date_from"],["history-to","date_to"]]){
      const value=byId(field).value.trim();
      if(value)params.set(key,value);
    }
    if(byId("history-from").value && byId("history-to").value &&
       byId("history-from").value>byId("history-to").value){
      throw new Error("Data końcowa nie może być wcześniejsza niż początkowa.");
    }
    const rows=await api("/api/history?"+params.toString());
    historyRows=rows;
    const container=byId("history-results");
    const actors=new Map();
    if(session.role==="admin"){
      try{
        const accounts=await api("/api/users");
        for(const u of accounts)actors.set(u.id,u.username);
      }catch(e){/* Historia nadal działa bez listy kont. */}
    }
    for(const row of rows)if(!actors.has(row.actor_id))actors.set(row.actor_id,row.actor_name);
    setOptions("history-actor",option("","Wszyscy użytkownicy")+
      [...actors.entries()].sort((a,b)=>String(a[1]).localeCompare(String(b[1]),"pl"))
        .map(([userId,userName])=>option(userId,userName)).join(""));
    if(!rows.length){
      container.innerHTML='<div class="empty borderless"><span class="empty-mark">'+icon("history")+'</span>'+
        '<h3>Brak wyników historii</h3><p>Zmień filtry albo poczekaj na kolejną operację magazynową.</p></div>';
      return;
    }
    const entries=rows.map(row=>
      '<tr><td data-label="Data (UTC)">'+esc((row.created_at||"").replace("T"," ").substring(0,19))+'</td>'+
      '<td data-label="Użytkownik">'+esc(row.actor_name)+'</td><td data-label="Operacja"><span class="pill secondary-pill">'+esc(actionLabels[row.action]||row.action)+'</span></td>'+
      '<td data-label="Produkt">'+esc(row.item_label)+'</td><td data-label="Ilość">'+fmt(row.quantity)+' szt.</td>'+
      '<td data-label="Lokalizacja">'+esc(row.location_code+(row.to_location_code?" → "+row.to_location_code:""))+'</td>'+
      '<td data-label="Powód">'+esc(reasonLabels[row.reason]||row.reason||"—")+'</td>'+
      '<td data-label="Akcje">'+(session.role==="admin"?'<button class="small edit-history" type="button" data-id="'+row.id+'">Edytuj</button> '+
      '<button class="small danger delete-history" type="button" data-id="'+row.id+'">Usuń</button>':"")+'</td></tr>').join("");
    container.innerHTML='<div class="table-wrap"><table class="history-table"><thead><tr>'+
      '<th>Data (UTC)</th><th>Użytkownik</th><th>Operacja</th><th>Produkt</th>'+
      '<th>Ilość</th><th>Lokalizacja</th><th>Powód</th><th>Administracja</th>'+
      '</tr></thead><tbody>'+entries+'</tbody></table></div>';
  }catch(e){toast(e.message,true);}
}

function openHistoryEditor(eventId){
  if(session?.role!=="admin")return;
  const row=historyRows.find(x=>x.id===eventId);
  if(!row){toast("Nie znaleziono wpisu historii.",true);return;}
  const form=byId("history-edit-form");
  for(const field of ["actor_name","item_label","action","quantity","location_code",
                      "created_at","before_source","after_source","reason","order_ref","note"]){
    form.elements.namedItem(field).value=row[field]??"";
  }
  form.elements.namedItem("event_id").value=String(eventId);
  byId("history-edit-dialog").showModal();
}

async function submitHistoryEditor(event){
  event.preventDefault();
  if(session?.role!=="admin")return;
  const form=event.currentTarget;
  if(!form.reportValidity())return;
  const values=Object.fromEntries(new FormData(form).entries());
  const id=Number(values.event_id);
  delete values.event_id;
  for(const name of ["quantity","before_source","after_source"]){
    values[name]=Number(values[name]);
    if(!Number.isSafeInteger(values[name])||values[name]<0||values[name]>2000000000){
      toast("Nieprawidłowa ilość w historii.",true);return;
    }
  }
  if(Number.isNaN(Date.parse(values.created_at))){
    toast("Nieprawidłowa data zdarzenia.",true);return;
  }
  const submit=form.querySelector('button[type="submit"]');submit.disabled=true;
  try{
    await api("/api/history/"+id,{method:"PATCH",body:JSON.stringify(values)});
    byId("history-edit-dialog").close();
    toast("Zmieniono wpis historii. Bieżący stan magazynu bez zmian.");
    await loadHistory();
  }catch(e){toast(e.message,true);}
  finally{submit.disabled=false;}
}


/* Product details and receiving/issuing */
function detailLine(label,value){
  if(!value)return "";
  return '<div class="detail-line"><strong>'+esc(label)+'</strong><span>'+esc(value)+'</span></div>';
}
function updateOperationTabs(action){
  byId("operation-action").value=action;
  for(const button of document.querySelectorAll(".action-choice")){
    const active=button.dataset.operation===action;
    button.classList.toggle("active",active);
    button.setAttribute("aria-pressed",String(active));
  }
  updateOperation();
}
function selectBalanceLocation(balance){
  const f=byId("operation-form");
  f.elements.location_id.value=String(balance.location_id);
  if(chosen?.kind==="ecu"){
    f.elements.product_state.value=balance.product_state;
    f.elements.technical_state.value=balance.technical_state;
  }
  updateOperation();
}
async function openItem(id, preferredAction="receive"){
  if(!session)return;
  const revision=++itemRevision;
  try{
    const details=await api("/api/items/"+id);
    if(revision!==itemRevision||!session)return;
    chosen=details;
    byId("detail-title").textContent=details.designation;
    byId("detail-kind").textContent=details.kind==="ecu"?
      (details.brand?"Sterownik · "+details.brand:"Sterownik"):"Elektronika";
    byId("detail-subtitle").textContent=[details.manufacturer,details.model,details.primary_number]
      .filter(Boolean).join(" · ");
    const numberList=(details.numbers||[]).map(n=>n.number).filter(x=>x!==details.primary_number);
    const lines=[
      ["Numer główny",details.primary_number],["Producent",details.manufacturer],
      ["Typ / model",details.model],["Numery dodatkowe",numberList.join(", ")],
      ["Marki",(details.brands||[]).join(", ")],
      ["HW / SW",[details.hw,details.sw].filter(Boolean).join(" / ")],
      ["Obudowa / parametry",details.kind==="ecu"?
        [details.package,details.parameters].filter(Boolean).join(" / "):""],
      ["Łącznie",fmt(details.total)+" szt."],
    ];
    const chips=details.balances.map((b,index)=>
      '<button type="button" class="balance-chip select-balance" data-index="'+index+'" '+
      'title="Ustaw tę lokalizację i stan do operacji">'+
      esc(b.location)+': '+fmt(b.quantity)+' szt.'+
      (details.kind==="ecu"?' · '+esc(stateLabels[b.product_state])+'/'+esc(stateLabels[b.technical_state]):"")+
      '</button>').join("");
    const folderControl='<div class="detail-folder-control"><label>Katalog produktu '+
      '<select id="detail-folder-select" '+(session.role==="admin"?"":"disabled")+'>'+
      folderOptions(details.kind,details.folder_id)+'</select></label>'+
      '<small class="muted">'+(session.role==="admin"?"Zmiana katalogu nie zmienia lokalizacji ani stanów.":"Zmiany katalogów wykonuje administrator.")+'</small></div>';
    byId("detail-content").innerHTML=folderControl+lines.map(([a,b])=>detailLine(a,b)).join("")+
      '<div class="balance-mini">'+(chips||'<span class="subtle-note">Brak sztuk na stanie</span>')+'</div>';
    byId("detail-folder-select").value=String(details.folder_id||"");
    renderElectronicDetails(details);
    const f=byId("operation-form");
    f.reset();
    f.elements.item_id.value=String(details.id);
    f.elements.quantity.value="1";
    const first=details.balances[0];
    if(first)selectBalanceLocation(first);
    document.querySelectorAll(".ecu-operation").forEach(node=>{
      node.hidden=details.kind!=="ecu";
    });
    byId("detail-admin").hidden=session.role!=="admin";
    const minimum=byId("minimum-form");
    minimum.reset();
    minimum.dataset.itemId="";
    minimum.querySelector("button[type=submit]").disabled=true;
    byId("minimum-notify").checked=false;
    byId("notify-details").hidden=true;
    byId("minimum-recipient").innerHTML=option("","Wybierz użytkownika");
    byId("minimum-provider").value="";
    byId("delete-item").dataset.id=String(details.id);
    updateOperationTabs(preferredAction);
    const dialog=byId("detail-dialog");
    if(!dialog.open)dialog.showModal();
    if(session.role==="admin")loadMinimumSettings(details.id);
  }catch(e){if(revision===itemRevision)toast(e.message,true);}
}
function updateOperation(){
  if(!chosen)return;
  const form=byId("operation-form");
  const action=form.elements.action.value;
  byId("reason-wrapper").hidden=action!=="issue";
  byId("order-wrapper").hidden=action!=="issue"||form.elements.reason.value!=="repair";
  byId("destination-wrapper").hidden=action!=="move";
  form.elements.reason.required=action==="issue";
  form.elements.quantity.min=action==="adjust"?"0":"1";
  const location=Number(form.elements.location_id.value);
  const productState=chosen.kind==="ecu"?form.elements.product_state.value:"na";
  const techState=chosen.kind==="ecu"?form.elements.technical_state.value:"na";
  const row=chosen.balances.find(b=>b.location_id===location &&
    b.product_state===productState&&b.technical_state===techState);
  const before=row?.quantity||0;
  const quantity=Number(form.elements.quantity.value);
  const validQty=Number.isSafeInteger(quantity) &&
    quantity >= (action==="adjust"?0:1) && quantity<=2_000_000_000;
  const result=action==="receive"?before+quantity:
    action==="adjust"?quantity:before-quantity;
  const sameDestination=action==="move" && form.elements.to_location_id.value===form.elements.location_id.value;
  const hasStock=action!=="issue" && action!=="move" || result>=0;
  const validLocation=locations.some(l=>l.id===location);
  const reasonOk=action!=="issue"||Boolean(form.elements.reason.value);
  const valid=validQty && validLocation && hasStock && !sameDestination && reasonOk &&
    result>=0 && result<=2_000_000_000;
  const preview=byId("operation-preview");
  preview.classList.toggle("invalid",!valid);
  const label=action==="receive"?"Po przyjęciu":action==="issue"?"Po wydaniu":
    action==="move"?"Po przeniesieniu":"Po korekcie";
  let caption=label+" · wybrany stan";
  let text=fmt(before)+" → "+(Number.isFinite(result)?fmt(result):"—")+" szt.";
  if(!valid){
    if(!validQty)caption="Podaj prawidłową ilość.";
    else if(!validLocation)caption="Wybierz lokalizację.";
    else if(!hasStock)caption="Niewystarczający stan w tej lokalizacji.";
    else if(sameDestination)caption="Lokalizacje muszą być różne.";
    else if(!reasonOk)caption="Wybierz powód wydania.";
    else caption="Sprawdź ilość.";
  }
  preview.innerHTML='<span class="preview-label">'+esc(caption)+'</span>'+
    '<span class="preview-number">'+esc(text)+'</span>';
  byId("operation-submit").disabled=!valid;
  byId("operation-submit").textContent=action==="receive"?"Zapisz przyjęcie":
    action==="issue"?"Potwierdź wydanie":action==="move"?"Przenieś sztuki":"Zapisz korektę";
}
async function submitOperation(event){
  event.preventDefault();
  if(!session||!chosen)return;
  const form=event.currentTarget;
  const action=form.elements.action.value;
  if(action==="adjust"&&session.role!=="admin")return toast("Korekta wymaga administratora",true);
  const data=Object.fromEntries(new FormData(form).entries());
  for(const field of ["item_id","location_id","to_location_id","quantity"]){
    data[field]=data[field]?Number(data[field]):null;
  }
  if(chosen.kind!=="ecu"){data.product_state="na";data.technical_state="na";}
  if(!Number.isSafeInteger(data.quantity))return toast("Nieprawidłowa ilość",true);
  const submit=byId("operation-submit");
  submit.disabled=true;
  try{
    await api("/api/stock",{method:"POST",body:JSON.stringify(data)});
    byId("detail-dialog").close();
    chosen=null;
    toast("Operacja została zapisana w historii magazynu.");
    await Promise.all([loadItems(),loadStats()]);
    if(!byId("page-low").hidden)loadLow();
    if(!byId("page-inventory").hidden)clearInventory();
  }catch(e){
    toast(e.message,true);
    // Reload changed quantities before allowing a repeat withdrawal.
    if(chosen){
      const id=chosen.id;
      try{chosen=await api("/api/items/"+id);}catch{}
    }
    updateOperation();
  }finally{if(!byId("detail-dialog").open)submit.disabled=false;}
}

/* New item: clear duplicate warnings and show one atomic add+receipt form */
function splitNumbers(value){
  return String(value||"").split(/[\n,;]+/).map(s=>s.trim()).filter(Boolean);
}
function setCreateKind(){
  const isEcu=byId("new-kind").value==="ecu";
  document.querySelectorAll("#item-dialog .ecu-field").forEach(node=>node.hidden=!isEcu);
  byId("new-brand").required=isEcu;
  scheduleSimilarCheck();
}
function openAddDialog(){
  if(!session)return;
  if(!locations.length&&session.role!=="admin"){
    toast("Administrator musi najpierw utworzyć lokalizację.",true);
    return;
  }
  const form=byId("item-form");
  form.reset();
  byId("new-quantity").value="1";
  populateFolderSelect("new-folder","ecu");
  byId("new-location").innerHTML=locationOptions();
  const firstLocation=!locations.length;
  byId("new-location").required=!firstLocation;
  byId("new-location").disabled=firstLocation;
  byId("quick-location-panel").hidden=!firstLocation;
  byId("ecu-first-location-help").hidden=!firstLocation;
  byId("new-location-toggle").hidden=firstLocation;
  byId("quick-location-code").required=firstLocation;
  byId("quick-location-save").hidden=firstLocation;
  byId("allow-variant").checked=false;
  similarCandidates=[];
  similarRevision++;
  clearTimeout(similarTimer);
  byId("similar-box").hidden=true;
  // When empty, an administrator can create the first location on submit.
  byId("item-submit").disabled=false;
  setCreateKind();
  byId("item-dialog").showModal();
  const nameInput=form.elements.primary_number;
  requestAnimationFrame(()=>nameInput.focus());
}
function getNewItemData(){
  const values=Object.fromEntries(new FormData(byId("item-form")).entries());
  const item={
    kind:values.kind,brand:values.kind==="ecu"?(values.brand||"").trim():"",
    designation:(values.designation||"").trim(),
    primary_number:(values.primary_number||"").trim(),
    manufacturer:(values.manufacturer||"").trim(),
    category:(values.category||"").trim(),
    model:(values.model||"").trim(),
    hw:(values.hw||"").trim(),
    sw:(values.sw||"").trim(),
    package:(values.package||"").trim(),
    parameters:(values.parameters||"").trim(),
    notes:(values.notes||"").trim(),
    brands:values.kind==="ecu"?splitNumbers(values.brands):[],
    numbers:splitNumbers(values.numbers).map(number=>({number,number_type:"other"})),
    location_id:Number(values.location_id)||null,
    new_location_code:!locations.length?byId("quick-location-code").value.trim():"",
    new_location_description:!locations.length?byId("quick-location-description").value.trim():"",
    quantity:Number(values.quantity),
    folder_id:Number(values.folder_id)||null,
    product_state:values.kind==="ecu"?values.product_state:"na",
    technical_state:values.kind==="ecu"?values.technical_state:"na",
    allow_distinct_variant:byId("allow-variant").checked,
  };
  return item;
}
function scheduleSimilarCheck(){
  similarRevision++;
  clearTimeout(similarTimer);
  const input=getNewItemData();
  const number=input.primary_number;
  const name=input.designation;
  if(!byId("item-dialog").open || (number.length<4&&name.length<3)){
    similarCandidates=[];
    byId("similar-box").hidden=true;
    // When empty, an administrator can create the first location on submit.
  byId("item-submit").disabled=false;
    return;
  }
  similarTimer=setTimeout(checkSimilar,370);
}
async function checkSimilar(){
  if(!byId("item-dialog").open)return;
  const current=++similarRevision;
  const data=getNewItemData();
  if(!data.kind || (!data.primary_number&&data.designation.length<3))return;
  const query=new URLSearchParams();
  for(const key of ["kind","designation","brand","manufacturer","model",
                    "primary_number","hw","sw","category","package","parameters"]){
    if(data[key])query.set(key,data[key]);
  }
  try{
    const rows=await api("/api/items/similar?"+query.toString());
    if(current!==similarRevision||!byId("item-dialog").open)return;
    similarCandidates=rows;
    renderSimilar();
  }catch(e){if(current===similarRevision)toast(e.message,true);}
}
function renderSimilar(){
  const box=byId("similar-box"),list=byId("similar-list"),checkbox=byId("allow-variant");
  if(!similarCandidates.length){
    box.hidden=true;
    checkbox.checked=false;
    // When empty, an administrator can create the first location on submit.
  byId("item-submit").disabled=false;
    return;
  }
  box.hidden=false;
  const exact=similarCandidates.some(item=>item.same_variant);
  byId("similar-spinner").textContent=exact?"Istniejący wariant":"Podobny wpis";
  list.innerHTML=similarCandidates.map(item=>
    '<div class="similar-item"><span><strong>'+esc(item.designation)+'</strong>'+
    '<small>'+esc([item.primary_number,item.hw?"HW "+item.hw:"",item.sw?"SW "+item.sw:""]
                    .filter(Boolean).join(" · "))+' · '+fmt(item.quantity)+' szt.</small></span>'+
    '<button type="button" class="small select-existing" data-id="'+item.id+'">Dodaj sztuki '+icon("arrow")+'</button></div>').join("");
  byId("allow-variant-label").hidden=exact;
  if(exact)checkbox.checked=false;
  byId("item-submit").disabled=exact || !checkbox.checked;
}
async function submitItem(event){
  event.preventDefault();
  const data=getNewItemData();
  if(!Number.isSafeInteger(data.quantity)||data.quantity<0||
     data.quantity>2_000_000_000){
    toast("Wpisz prawidłową ilość sztuk.",true);return;
  }
  if(!data.location_id&&!data.new_location_code){
    toast("Wpisz kod pierwszej lokalizacji magazynowej, np. A1.",true);
    byId("quick-location-panel").hidden=false;
    byId("quick-location-code").focus();
    return;
  }
  if(!data.designation)return toast("Uzupełnij nazwę produktu.",true);
  if(data.kind==="ecu"&&!data.brand)return toast("Wybierz markę pojazdu.",true);
  if(similarCandidates.some(x=>x.same_variant)){
    toast("Ten wariant już istnieje. Użyj przycisku „Dodaj sztuki”.",true);
    return;
  }
  if(similarCandidates.length&&!data.allow_distinct_variant){
    toast("Sprawdź zbliżone pozycje przed dodaniem nowego wariantu.",true);
    return;
  }
  const button=byId("item-submit");
  button.disabled=true;
  try{
    const created=await api("/api/items/receive",{method:"POST",body:JSON.stringify(data)});
    byId("item-dialog").close();
    toast("Dodano produkt i "+fmt(created.quantity)+" szt. w jednej operacji.");
    if(data.new_location_code)await loadLocations();
    await Promise.all([loadItems(),loadStats(),loadBrands()]);
  }catch(e){
    toast(e.message,true);
    if(e.message.includes("istnieje")||e.message.includes("podobny")||e.message.includes("wariant")){
      await checkSimilar();
    }
  }finally{if(byId("item-dialog").open)renderSimilar();}
}
async function saveQuickLocation(){
  if(!session||session.role!=="admin")return;
  const code=byId("quick-location-code").value.trim();
  const description=byId("quick-location-description").value.trim();
  if(!code)return toast("Podaj kod lokalizacji.",true);
  const button=byId("quick-location-save");
  button.disabled=true;
  try{
    const created=await api("/api/locations",{method:"POST",body:JSON.stringify({code,description})});
    await loadLocations();
    byId("new-location").value=String(created.id);
    byId("quick-location-panel").hidden=true;
    byId("quick-location-code").value="";
    byId("quick-location-description").value="";
    byId("item-submit").disabled=similarCandidates.some(x=>x.same_variant)||
      (similarCandidates.length&&!byId("allow-variant").checked);
    toast("Dodano lokalizację "+code);
    loadStats();
  }catch(e){toast(e.message,true);}
  finally{button.disabled=false;}
}


/* Low-stock alerts: only individually linked, verified user accounts. */
function populateRecipientOptions(provider, selected=""){
  const select=byId("minimum-recipient");
  const validIds=new Set(linkedAccounts.filter(a=>a.active&&a.provider===provider).map(a=>String(a.user_id)));
  const linkedUsers=usersCache.filter(u=>u.active&&validIds.has(String(u.id)));
  select.innerHTML=option("","Wybierz użytkownika")+
    linkedUsers.map(u=>option(u.id,u.username)).join("");
  if(selected && validIds.has(String(selected)))select.value=String(selected);
  else select.value="";
  const hint=byId("notify-help");
  hint.textContent=linkedUsers.length?
    "Alert trafi wyłącznie na prywatne konto wybranego użytkownika. Nie jest wysyłany grupowo.":
    "Brak powiązanego konta "+(provider==="discord"?"Discord":"Telegram")+
    ". Połącz pracownika w Ustawieniach, zanim włączysz alert.";
}
function toggleNotify(show){
  byId("notify-details").hidden=!show;
  const provider=byId("minimum-provider");
  if(show&&!provider.value)provider.value="telegram";
  populateRecipientOptions(provider.value,byId("minimum-recipient").value);
}
async function loadMinimumSettings(itemId){
  try{
    const [minimum,users,links]=await Promise.all([
      api("/api/items/"+itemId+"/minimum"),
      api("/api/users"),
      api("/api/messaging/links"),
    ]);
    if(!chosen||chosen.id!==itemId||!byId("detail-dialog").open||session?.role!=="admin")return;
    usersCache=users;linkedAccounts=links;
    const form=byId("minimum-form");
    form.elements.minimum.value=minimum.minimum===null?"0":String(minimum.minimum);
    const enabled=Boolean(minimum.provider&&minimum.recipient_user_id);
    byId("minimum-notify").checked=enabled;
    byId("minimum-provider").value=minimum.provider||"";
    byId("notify-details").hidden=!enabled;
    populateRecipientOptions(minimum.provider||"telegram",minimum.recipient_user_id);
    form.dataset.itemId=String(itemId);
    form.querySelector("button[type=submit]").disabled=false;
  }catch(e){toast("Nie udało się pobrać ustawień: "+e.message,true);}
}
async function formMinimum(event){
  event.preventDefault();
  const form=event.currentTarget;
  if(!chosen||form.dataset.itemId!==String(chosen.id)){
    toast("Odśwież szczegóły produktu przed zapisem.",true);return;
  }
  const minimum=Number(form.elements.minimum.value);
  if(!Number.isSafeInteger(minimum)||minimum<0)return toast("Wpisz poprawny stan minimalny.",true);
  const enabled=byId("minimum-notify").checked;
  const provider=enabled?form.elements.provider.value:"";
  const recipient=enabled?form.elements.recipient_user_id.value:"";
  if(enabled&&(!provider||!recipient)){
    toast("Najpierw wybierz komunikator i powiązanego użytkownika.",true);return;
  }
  const button=form.querySelector("button[type=submit]");
  button.disabled=true;
  try{
    const id=chosen.id;
    await api("/api/items/"+id+"/minimum",{method:"PUT",body:JSON.stringify({
      minimum,provider,recipient_user_id:recipient?Number(recipient):null,
    })});
    toast(enabled?"Ustawiono minimum i prywatne powiadomienie.":"Zapisano stan minimalny bez powiadomień.");
    await loadMinimumSettings(id);
    await loadStats();
    if(!byId("page-low").hidden)loadLow();
  }catch(e){toast(e.message,true);}
  finally{if(form.dataset.itemId===String(chosen?.id))button.disabled=false;}
}

/* Administrator workspace */
async function loadAdmin(){
  if(!session||session.role!=="admin")return;
  try{
    const users=await api("/api/users");
    usersCache=users;
    byId("users-list").innerHTML=users.map(u=>
      '<div class="list-row"><div><strong>'+esc(u.username)+'</strong> <span class="tag">'+
      (u.role==="admin"?"Administrator":"Pracownik")+'</span>'+
      (u.active?"":'<span class="pill warning-pill">Zablokowany</span>')+'</div>'+
      '<div class="action-row"><button class="small rename-user" type="button" data-id="'+u.id+'">Zmień login</button>'+
      (u.role==="user"?'<button class="small reset-staff-password" type="button" data-id="'+u.id+'">Resetuj hasło</button>':"")+
      '<button class="small toggle-user" type="button" data-id="'+u.id+'" data-active="'+u.active+'">'+
      (u.active?"Zablokuj":"Aktywuj")+'</button></div></div>').join("");
    byId("locations-list").innerHTML=locations.length?locations.map(x=>
      '<div class="list-row"><div><strong>'+esc(x.code)+'</strong>'+
      (x.description?'<div class="muted small-text">'+esc(x.description)+'</div>':"")+'</div></div>').join(""):
      '<p class="subtle-note">Brak miejsc składowania. Utwórz pierwsze poniżej.</p>';
  }catch(e){toast(e.message,true);}
}
async function formUser(event){
  event.preventDefault();
  const form=event.currentTarget;
  const data=Object.fromEntries(new FormData(form).entries());
  const button=form.querySelector("button[type=submit]");
  button.disabled=true;
  try{
    await api("/api/users",{method:"POST",body:JSON.stringify(data)});
    form.reset();
    toast("Utworzono konto pracownika. Przekaż mu dane logowania prywatnie.");
    await Promise.all([loadAdmin(),loadMessagingUi()]);
  }catch(e){toast(e.message,true);}
  finally{button.disabled=false;}
}
async function formLocation(event){
  event.preventDefault();
  const form=event.currentTarget;
  const data=Object.fromEntries(new FormData(form).entries());
  try{
    await api("/api/locations",{method:"POST",body:JSON.stringify(data)});
    form.reset();
    await Promise.all([loadLocations(),loadStats()]);
    loadAdmin();
    toast("Dodano lokalizację "+data.code);
  }catch(e){toast(e.message,true);}
}
async function loadMessagingUi(){
  if(!session||session.role!=="admin")return;
  try{
    const [accounts,users,status]=await Promise.all([
      api("/api/messaging/links"),api("/api/users"),api("/api/messaging/status")]);
    if(!session||session.role!=="admin")return;
    linkedAccounts=accounts;usersCache=users;
    const select=byId("pairing-user"),previous=select.value;
    select.innerHTML=users.filter(u=>u.active).map(u=>option(u.id,u.username)).join("");
    if(users.some(u=>String(u.id)===previous&&u.active))select.value=previous;
    const list=byId("messaging-links");
    list.replaceChildren();
    if(!accounts.length)list.textContent="Nie powiązano jeszcze żadnego konta komunikatora.";
    for(const account of accounts){
      const row=document.createElement("div");
      row.className="list-row";
      const title=document.createElement("div");
      const person=document.createElement("strong");
      person.textContent=account.username;
      const state=document.createElement("span");
      state.className="pill secondary-pill";
      state.textContent=" · "+account.provider+" · zweryfikowane";
      title.append(person,state);
      const action=document.createElement("button");
      action.type="button";action.className="small danger";
      action.textContent="Odłącz";
      action.addEventListener("click",async()=>{
        if(!confirm("Odłączyć prywatne konto "+account.provider+" użytkownika "+account.username+"?"))return;
        try{
          await api("/api/messaging/links/"+account.provider+"/"+account.user_id,
                    {method:"DELETE",body:"{}"});
          toast("Odłączono konto.");
          loadMessagingUi();
        }catch(e){toast(e.message,true);}
      });
      row.append(title,action);list.append(row);
    }
    const counts=status.outbox||{};
    byId("messaging-summary").textContent=
      "Powiadomienia: oczekujące "+(counts.pending||0)+
      " · wysłane "+(counts.sent||0)+
      " · anulowane "+(counts.cancelled||0)+".";
  }catch(e){toast(e.message,true);}
}
async function formPairing(event){
  event.preventDefault();
  const form=event.currentTarget,data=Object.fromEntries(new FormData(form).entries());
  const output=byId("pairing-result");
  output.hidden=true;output.textContent="";
  if(!data.user_id)return toast("Wybierz użytkownika.",true);
  try{
    const result=await api("/api/messaging/pairing",{method:"POST",body:JSON.stringify({
      user_id:Number(data.user_id),provider:data.provider,
    })});
    output.textContent="Dla użytkownika "+result.username+
      " wyślij w prywatnej rozmowie z botem: /polacz "+result.code+
      ". Kod jednorazowy, ważny do "+result.expires_at+".";
    output.hidden=false;
    toast("Wygenerowano prywatny kod powiązania.");
  }catch(e){toast(e.message,true);}
}
async function loadBackupStatus(){
  if(!session||session.role!=="admin")return;
  try{
    const status=await api("/api/backup/status");
    byId("backup-status").textContent=!status.configured?
      "Backup nie jest jeszcze skonfigurowany. Brak aktywnego harmonogramu.":
      "Kopie w lokalnym buforze: "+(status.pending||0)+
      ". Ostatnia lokalna: "+(status.last_local_backup||"brak")+
      ". Ostatnia wysłana do GlobalNAS: "+(status.last_synced_at||"brak")+"."+
      (status.bridge_health?" Ostatnia kontrola kopii Magazynu: "+status.bridge_health+
        " ("+(status.bridge_last_check_at||"brak daty")+").":"")+
      (status.pending&&status.bridge_oldest_pending_hours!=null?
        " Najstarsza zaległa kopia: "+status.bridge_oldest_pending_hours+" h.":"")+
      (status.last_error?" Problem backupu: "+status.last_error:"");
  }catch(e){byId("backup-status").textContent="Nie można pobrać statusu: "+e.message;}
}
async function loadBackupArchives(){
  if(session?.role!=="admin")return;
  try{
    const result=await api("/api/backup/archives");
    backupArchiveRows=result.archives||[];
    const options=backupArchiveRows.map((row,i)=>option(
      i,(row.source==="nas"?"GlobalNAS":"Bufor lokalny")+" / "+
        row.tier+" / "+row.name.substring(0,15))).join("");
    setOptions("backup-archive-select",option("","Wybierz kopię") + options,false);
    byId("backup-restore-result").textContent=result.nas_online?
      "GlobalNAS dostępny. Znaleziono archiwów: "+backupArchiveRows.length+".":
      "GlobalNAS niedostępny. Można sprawdzać kopie pozostawione w lokalnym buforze.";
  }catch(e){byId("backup-restore-result").textContent="Nie można odczytać listy: "+e.message;}
}
async function runBackupRestoreTest(){
  if(session?.role!=="admin")return;
  const index=byId("backup-archive-select").value;
  if(index===""){toast("Wybierz kopię do kontroli.",true);return;}
  const row=backupArchiveRows[Number(index)];
  if(!row)return;
  if(!confirm("Sprawdzić odtworzenie archiwum w RAM? Baza robocza pozostanie bez zmian."))return;
  const button=byId("backup-restore-test");button.disabled=true;
  try{
    const result=await api("/api/backup/restore-check",{
      method:"POST",body:JSON.stringify({source:row.source,tier:row.tier,name:row.name})});
    byId("backup-restore-result").textContent=
      "PASS: archiwum "+result.name+" odtworzono w RAM, integralność "+result.integrity+
      ". Kopia tymczasowa usunięta; działająca baza bez zmian.";
  }catch(e){byId("backup-restore-result").textContent="FAIL: "+e.message;toast(e.message,true);}
  finally{button.disabled=false;}
}

/* Inventory counting by location */
function clearInventory(){
  inventoryRequest++;inventoryRows=[];inventoryLocation=null;
  byId("inventory-results").replaceChildren();
  byId("inventory-apply").disabled=true;
}
async function loadInventory(){
  clearInventory();
  const revision=inventoryRequest,location=Number(byId("inventory-location").value),user=session;
  if(!location)return toast("Wybierz lokalizację.",true);
  try{
    const rows=await api("/api/inventory?location_id="+location);
    if(revision!==inventoryRequest||user!==session)return;
    inventoryRows=rows;inventoryLocation=location;
    const container=byId("inventory-results");
    if(!rows.length){
      container.innerHTML='<div class="empty"><span class="empty-mark">'+icon("box")+'</span>'+
        '<h3>Brak pozycji do policzenia</h3><p>Najpierw dodaj produkty do katalogu.</p></div>';
      return;
    }
    container.innerHTML='<table><thead><tr><th>Produkt</th><th>Stan</th><th>Sprawność</th>'+
      '<th>Oczekiwane</th><th>Policzone</th><th>Różnica</th></tr></thead><tbody>'+
      rows.map((row,index)=>
        '<tr><td data-label="Produkt"><strong>'+esc(row.designation)+'</strong></td><td data-label="Stan">'+
        esc(stateLabels[row.product_state]||row.product_state)+'</td><td data-label="Sprawność">'+
        esc(stateLabels[row.technical_state]||row.technical_state)+'</td><td data-label="Oczekiwane">'+
        fmt(row.expected_quantity)+'</td><td data-label="Policzone"><input class="inventory-count" type="number" '+
        'min="0" step="1" max="2000000000" inputmode="numeric" enterkeyhint="done" data-index="'+index+'" placeholder="Bez zmian" '+
        'aria-label="Policzone sztuki: '+esc(row.designation)+'" '+(session.role==="admin"?"":"disabled")+
        '></td><td data-label="Różnica" class="inventory-delta">—</td></tr>').join("")+'</tbody></table>';
    byId("inventory-apply").disabled=session.role!=="admin";
  }catch(e){toast(e.message,true);}
}
async function applyInventory(event){
  event.preventDefault();
  if(!session||session.role!=="admin")return;
  const rows=[];
  for(const input of document.querySelectorAll(".inventory-count")){
    if(input.value==="")continue;
    const counted=Number(input.value);
    if(!Number.isSafeInteger(counted)||counted<0||counted>2_000_000_000)
      return toast("Sprawdź policzone ilości.",true);
    const {designation,...row}=inventoryRows[Number(input.dataset.index)];
    rows.push({...row,quantity:counted});
  }
  if(!rows.length||rows.length>1000){
    toast("Wpisz ilości dla od 1 do 1000 pozycji.",true);return;
  }
  if(!confirm("Zastosować korekty dla "+rows.length+" pozycji?"))return;
  const button=byId("inventory-apply");button.disabled=true;
  try{
    await api("/api/inventory",{method:"POST",body:JSON.stringify({
      location_id:inventoryLocation,rows,
    })});
    toast("Zapisano inwentaryzację i historię korekt.");
    await Promise.all([loadInventory(),loadStats()]);
  }catch(e){
    toast(e.message+". Jeśli stan się zmienił, odśwież inwentaryzację.",true);
    button.disabled=false;
  }
}

/* Import/export: unchanged formats, preview must precede write */
function clearImport(){
  importUpload=null;
  byId("import-apply").disabled=true;
  byId("import-results").replaceChildren();
}
async function downloadTable(path,filename){
  try{
    const response=await fetch(path,{credentials:"same-origin"});
    if(!response.ok){
      let detail={};
      try{detail=await response.json();}catch{}
      throw new Error(parseError(detail,response.status));
    }
    const url=URL.createObjectURL(await response.blob());
    const anchor=document.createElement("a");
    anchor.href=url;anchor.download=filename;document.body.append(anchor);anchor.click();anchor.remove();
    setTimeout(()=>URL.revokeObjectURL(url),2000);
  }catch(e){toast(e.message,true);}
}
async function importPreview(){
  clearImport();
  const file=byId("import-file").files[0],user=session;
  if(!file||file.size>1000000)return toast("Wybierz plik CSV/Excel do 1 MB.",true);
  const type=file.name.split(".").pop().toLowerCase();
  if(!["csv","xlsx"].includes(type))return toast("Obsługiwane formaty: CSV i Excel (.xlsx).",true);
  const button=byId("import-preview");button.disabled=true;
  try{
    const bytes=new Uint8Array(await file.arrayBuffer());
    let binary="";
    for(const byte of bytes)binary+=String.fromCharCode(byte);
    const upload={format:type,content_base64:btoa(binary)};
    const result=await api("/api/import/preview",{method:"POST",body:JSON.stringify(upload)});
    if(session!==user||file!==byId("import-file").files[0])return;
    const display=byId("import-results");
    display.textContent="Pozycji: "+result.count+" · Poprawnych: "+result.valid_count+
      " · Problemów: "+result.problems.length+".";
    for(const problem of result.problems){
      const row=document.createElement("p");
      row.textContent="Wiersz "+problem.row+": "+problem.detail;
      display.append(row);
    }
    if(result.token){
      importUpload={...upload,token:result.token};
      byId("import-apply").disabled=false;
    }
  }catch(e){toast(e.message,true);}
  finally{button.disabled=false;}
}
async function importApply(){
  if(!importUpload)return;
  const data=importUpload,button=byId("import-apply");button.disabled=true;
  try{
    const result=await api("/api/import/apply",{method:"POST",body:JSON.stringify(data)});
    clearImport();
    byId("import-results").textContent="Zaimportowano "+result.count+" nowych produktów.";
    byId("import-file").value="";
    toast("Import został pomyślnie zakończony.");
    await Promise.all([loadItems(),loadStats(),loadBrands()]);
    clearInventory();
  }catch(e){clearImport();toast(e.message+" Wykonaj podgląd ponownie.",true);}
}


/* One wiring point for the whole interface. */
document.addEventListener("DOMContentLoaded",async()=>{
  const login=byId("login-form");
  login.addEventListener("submit",async event=>{
    event.preventDefault();
    const data=Object.fromEntries(new FormData(login).entries());
    const button=login.querySelector("button[type=submit]");
    button.disabled=true;
    try{
      const user=await api("/api/auth/login",{method:"POST",body:JSON.stringify(data)});
      setSignedIn(user);
      await Promise.all([loadLocations(),loadStats(),loadBrands(),loadFolders()]);
      await loadItems();
      login.elements.password.value="";
    }catch(e){toast(e.message,true);}
    finally{button.disabled=false;}
  });
  byId("logout").addEventListener("click",async()=>{
    try{await api("/api/auth/logout",{method:"POST",body:"{}"});}catch{}
    showLogin();
  });
  document.querySelectorAll(".nav-item").forEach(button=>{
    button.addEventListener("click",()=>showTab(button.dataset.tab));
  });
  // Settings shortcuts: immediate in-page navigation, without server calls.
  // Explicit scrolling prevents the sticky phone header from hiding a target.
  document.querySelectorAll(".settings-shortcuts a").forEach(link=>{
    link.addEventListener("click",event=>{
      const target=document.getElementById(link.hash.slice(1));
      if(!target)return;
      event.preventDefault();
      if(target.tagName==="DETAILS")target.open=true;
      history.replaceState(null,"","#"+target.id);
      target.scrollIntoView({block:"start",behavior:"instant"});
    });
  });
  byId("show-add").addEventListener("click",openAddDialog);
  byId("low-refresh").addEventListener("click",loadLow);
  for(const button of document.querySelectorAll(".close-dialog")){
    button.addEventListener("click",()=>button.closest("dialog").close());
  }
  for(const dialog of document.querySelectorAll("dialog")){
    dialog.addEventListener("close",()=>{
      if(dialog.id==="detail-dialog"){chosen=null;itemRevision++;}
      if(dialog.id==="item-dialog"){
        similarRevision++;similarCandidates=[];clearTimeout(similarTimer);
      }
    });
  }
  byId("filter-toggle").addEventListener("click",()=>{
    const panel=byId("advanced-filters");
    panel.hidden=!panel.hidden;
    byId("filter-toggle").setAttribute("aria-expanded",String(!panel.hidden));
  });
  for(const button of document.querySelectorAll(".kind-choice")){
    button.addEventListener("click",()=>{
      byId("filter-kind").value=button.dataset.kind;
      updateKindButtons(button.dataset.kind);
      loadItems();
    });
  }
  byId("clear-filters").addEventListener("click",resetAllFilters);
  const fields=["filter-kind","filter-brand","filter-product-state","filter-tech-state","filter-location"];
  for(const id of fields){
    byId(id).addEventListener("change",()=>{
      if(id==="filter-kind")updateKindButtons(byId(id).value);
      loadItems();
    });
  }
  let searchTimer;
  byId("search").addEventListener("input",()=>{
    clearTimeout(searchTimer);
    searchTimer=setTimeout(loadItems,180);
  });
  document.addEventListener("keydown",event=>{
    if(event.key!=="/"||event.ctrlKey||event.metaKey||event.altKey||
       event.target.closest("input,textarea,select,[contenteditable=true]")||
       document.querySelector("dialog[open]")||byId("app").hidden)return;
    event.preventDefault();
    showTab("products");
    byId("search").focus();
  });

  byId("new-kind").addEventListener("change",setCreateKind);
  byId("item-form").addEventListener("input",event=>{
    const name=event.target.name;
    if(name==="allow_distinct_variant"){renderSimilar();return;}
    if(["kind","brand","designation","primary_number","manufacturer","model",
        "hw","sw","category","package","parameters","numbers"].includes(name)){
      scheduleSimilarCheck();
    }
    if(name==="quantity"||name==="location_id"){
      byId("item-submit").disabled=similarCandidates.some(x=>x.same_variant)||
        (similarCandidates.length&&!byId("allow-variant").checked);
    }
  });
  byId("item-form").addEventListener("submit",submitItem);
  byId("new-location-toggle").addEventListener("click",()=>{
    const panel=byId("quick-location-panel");
    panel.hidden=!panel.hidden;
    if(!panel.hidden)byId("quick-location-code").focus();
  });
  byId("quick-location-save").addEventListener("click",saveQuickLocation);
  byId("allow-variant").addEventListener("change",renderSimilar);
  byId("operation-form").addEventListener("input",updateOperation);
  byId("operation-form").addEventListener("change",updateOperation);
  byId("operation-form").addEventListener("submit",submitOperation);
  for(const button of document.querySelectorAll(".action-choice")){
    button.addEventListener("click",()=>{
      if(button.dataset.operation==="adjust"&&session?.role!=="admin")return;
      updateOperationTabs(button.dataset.operation);
    });
  }
  for(const button of document.querySelectorAll(".stepper-btn")){
    button.addEventListener("click",()=>{
      const input=byId(button.dataset.qtyTarget);
      if(!input)return;
      const step=Number(button.dataset.step);
      const min=Number(input.min)||0;
      const max=Number(input.max)||2_000_000_000;
      let number=Number(input.value)||0;
      number=Math.min(max,Math.max(min,number+step));
      input.value=String(number);
      input.dispatchEvent(new Event("input",{bubbles:true}));
    });
  }
  byId("detail-content").addEventListener("change",async event=>{
    if(event.target.id!=="detail-folder-select"||!chosen||session?.role!=="admin")return;
    const select=event.target,old=chosen.folder_id;
    select.disabled=true;
    try{
      const folder_id=Number(select.value)||null;
      await api("/api/items/"+chosen.id+"/folder",{method:"PUT",body:JSON.stringify({folder_id})});
      chosen.folder_id=folder_id;
      toast("Przeniesiono produkt do katalogu.");
      await loadItems();
    }catch(error){
      select.value=String(old||"");
      toast(error.message,true);
    }finally{select.disabled=false;}
  });
  byId("detail-content").addEventListener("click",event=>{
    const button=event.target.closest(".select-balance");
    if(!button||!chosen)return;
    const row=chosen.balances[Number(button.dataset.index)];
    if(row)selectBalanceLocation(row);
  });
  byId("minimum-notify").addEventListener("change",event=>{
    toggleNotify(event.target.checked);
  });
  byId("minimum-provider").addEventListener("change",event=>{
    populateRecipientOptions(event.target.value);
  });
  byId("minimum-form").addEventListener("submit",formMinimum);
  byId("delete-item").addEventListener("click",async()=>{
    if(!session||session.role!=="admin"||!chosen)return;
    const id=chosen.id;
    if(!confirm("Trwale usunąć produkt „"+chosen.designation+"” i wszystkie jego stany?"))return;
    try{
      await api("/api/items/"+id,{method:"DELETE",body:"{}"});
      byId("detail-dialog").close();
      toast("Produkt został usunięty.");
      await Promise.all([loadItems(),loadStats(),loadBrands()]);
    }catch(e){toast(e.message,true);}
  });

  byId("inventory-location").addEventListener("change",clearInventory);
  byId("inventory-load").addEventListener("click",loadInventory);
  byId("inventory-form").addEventListener("submit",applyInventory);
  byId("inventory-results").addEventListener("input",event=>{
    const input=event.target;
    if(!input.classList.contains("inventory-count"))return;
    const row=inventoryRows[Number(input.dataset.index)];
    input.closest("tr").querySelector(".inventory-delta").textContent=
      input.value===""?"—":String(Number(input.value)-row.expected_quantity);
  });

  byId("location-form").addEventListener("submit",formLocation);
  setupFolderUI();
  byId("user-form").addEventListener("submit",formUser);
  byId("pairing-form").addEventListener("submit",formPairing);
  byId("history-filters").addEventListener("submit",event=>{
    event.preventDefault();loadHistory();
  });
  byId("history-clear").addEventListener("click",()=>{
    for(const field of ["history-query","history-actor","history-from","history-to"])byId(field).value="";
    loadHistory();
  });
  byId("history-edit-form").addEventListener("submit",submitHistoryEditor);
  byId("backup-refresh").addEventListener("click",loadBackupStatus);
  byId("backup-archives-refresh").addEventListener("click",loadBackupArchives);
  byId("backup-restore-test").addEventListener("click",runBackupRestoreTest);
  byId("backup-manual").addEventListener("click",async()=>{
    if(!confirm("Utworzyć zaszyfrowaną kopię w lokalnym buforze?"))return;
    const button=byId("backup-manual");button.disabled=true;
    try{
      const result=await api("/api/backup/manual",{method:"POST",body:"{}"});
      toast("Kopia lokalna utworzona. Oczekujące na NAS: "+result.pending);
      await loadBackupStatus();
    }catch(e){toast(e.message,true);}finally{button.disabled=false;}
  });
  for(const type of ["csv","xlsx"]){
    byId("export-"+type).addEventListener("click",()=>{
      const query=new URLSearchParams({format:type});
      if(byId("export-kind").value)query.set("kind",byId("export-kind").value);
      if(byId("export-brand").value.trim())query.set("brand",byId("export-brand").value.trim());
      downloadTable("/api/export?"+query,"magazyn-snapshot."+type);
    });
    byId("template-"+type).addEventListener("click",()=>{
      downloadTable("/api/import/template?format="+type,"magazyn-new."+type);
    });
  }
  byId("import-file").addEventListener("change",clearImport);
  byId("import-preview").addEventListener("click",importPreview);
  byId("import-apply").addEventListener("click",importApply);

  document.addEventListener("click",async event=>{
    const reset=event.target.closest('[data-ui="clear-filters"]');
    if(reset){resetAllFilters();return;}
    const add=event.target.closest('[data-ui="add-first"]');
    if(add){openAddDialog();return;}
    const existing=event.target.closest(".select-existing");
    if(existing){
      byId("item-dialog").close();
      openItem(Number(existing.dataset.id),"receive");
      return;
    }
    const elem=event.target.closest("[data-id]");
    if(!elem||!session)return;
    const id=Number(elem.dataset.id);
    if(elem.classList.contains("open-item"))return openItem(id);
    if(elem.classList.contains("quick-receive"))return openItem(id,"receive");
    if(elem.classList.contains("quick-issue"))return openItem(id,"issue");
    if(elem.classList.contains("edit-history")){
      openHistoryEditor(id);
      return;
    }
    if(elem.classList.contains("delete-history")){
      if(session.role!=="admin"||!confirm("Usunąć ten wpis historii?"))return;
      try{
        await api("/api/history/"+id,{method:"DELETE",body:"{}"});
        toast("Usunięto wpis historii.");
        loadHistory();
      }catch(e){toast(e.message,true);}
      return;
    }
    if(elem.classList.contains("toggle-user")){
      if(session.role!=="admin")return;
      const active=elem.dataset.active==="1";
      const user=usersCache.find(u=>u.id===id);
      if(!user||!confirm((active?"Zablokować":"Aktywować")+" konto "+user.username+"?"))return;
      try{
        await api("/api/users/"+id,{method:"PATCH",body:JSON.stringify({active:!active})});
        toast("Zmieniono status konta.");
        await Promise.all([loadAdmin(),loadMessagingUi()]);
      }catch(e){toast(e.message,true);}
      return;
    }
    if(elem.classList.contains("rename-user")){
      if(session.role!=="admin")return;
      const user=usersCache.find(u=>u.id===id);if(!user)return;
      const value=prompt("Nowy login użytkownika "+user.username+":",user.username);
      if(value===null||!value.trim()||value.trim()===user.username)return;
      try{
        await api("/api/users/"+id,{method:"PATCH",body:JSON.stringify({username:value.trim()})});
        toast("Login został zmieniony.");
        if(session.id===id){
          const me=await api("/api/auth/me");
          session=me;
          byId("current-user").textContent=me.username;
          byId("user-avatar").textContent=me.username[0].toUpperCase();
        }
        await Promise.all([loadAdmin(),loadMessagingUi()]);
      }catch(e){toast(e.message,true);}
    }
  });
  try{
    const user=await api("/api/auth/me");
    setSignedIn(user);
    await Promise.all([loadLocations(),loadStats(),loadBrands(),loadFolders()]);
    await loadItems();
  }catch{
    showLogin();
  }
});
