"use strict";

/* Dedicated read-only supplier quote view. No inventory/ordering side effects. */
let supplierCompareRevision=0;
const compareSupplierNames={tme:"TME",mouser:"Mouser"};
const compareStatusLabels={
  ok:"Odpowiedź API",partial:"Częściowe dane – nie udało się pobrać części cen lub stanów",
  disabled:"Hurtownia wyłączona",credentials_required:"Brak konfiguracji API",
  offline_dev:"Zapytania LIVE wyłączone",api_error:"Błąd API hurtowni"
};
const compareNumber=n=>new Intl.NumberFormat("pl-PL").format(n);

function resetSupplierComparison(){
  supplierCompareRevision++;
  const form=byId("compare-search-form"),results=byId("compare-results");
  if(form)form.reset();
  if(results)results.replaceChildren();
  const status=byId("compare-status");
  if(status)status.textContent="Wpisz oznaczenie i rozpocznij wyszukiwanie.";
  const button=byId("compare-search-button");
  if(button)button.disabled=false;
}
function compareUrl(value){
  if(typeof value!=="string")return "";
  try{
    const u=new URL(value);
    const h=u.hostname.toLowerCase();
    if(u.protocol==="https:" &&
       ["tme.eu","www.tme.eu","mouser.com","www.mouser.com",
        "mouser.pl","www.mouser.pl","eu.mouser.com"].includes(h) &&
       !u.username&&!u.password&&u.port===""&&!u.hash)return u.href;
  }catch{}
  return "";
}
function comparePrice(row){
  const tiers=Array.isArray(row.price_breaks)?row.price_breaks:[];
  if(!tiers.length)return '<span class="muted">Brak danych</span>';
  const first=tiers[0];
  const money=tier=>{
    const raw=String(tier.price||""),currency=String(row.currency||"");
    const already=(currency&&raw.toUpperCase().includes(currency.toUpperCase()))||
      (currency==="PLN"&&/zł/i.test(raw))||
      (currency==="USD"&&raw.includes("$"))||
      (currency==="EUR"&&raw.includes("€"))||
      (currency==="GBP"&&raw.includes("£"));
    return esc(raw)+(currency&&!already?" "+esc(currency):"");
  };
  const tax=row.price_type==="NET"?"netto":row.price_type==="GROSS"?"brutto":"";
  const firstLabel='<strong class="compare-price">'+money(first)+'</strong>'+
    '<small class="muted">od '+compareNumber(first.quantity)+' szt.'+(tax?" · "+tax:"")+'</small>';
  if(tiers.length===1)return '<div class="compare-price-cell">'+firstLabel+'</div>';
  return '<div class="compare-price-cell">'+firstLabel+
    '<details class="compare-tiers"><summary>'+tiers.length+' progi cenowe</summary>'+
    '<ul>'+tiers.map(t=>'<li><span>od '+compareNumber(t.quantity)+' szt.</span><strong>'+
       money(t)+'</strong></li>').join("")+'</ul></details></div>';
}
function compareStock(row){
  if(Number.isSafeInteger(row.stock_quantity)&&row.stock_quantity>=0){
    return '<strong class="compare-stock '+(row.stock_quantity>0?"in-stock":"out-stock")+'">'+
      compareNumber(row.stock_quantity)+' szt.</strong>'+
      (row.stock_text?'<small class="muted">'+esc(row.stock_text)+'</small>':"");
  }
  return '<strong class="muted">Brak liczby</strong>'+
    (row.stock_text?'<small class="muted">'+esc(row.stock_text)+'</small>':"");
}
function compareResultRow(row){
  const name=compareSupplierNames[row.supplier]||row.supplier;
  const link=compareUrl(row.product_url);
  return '<tr><td data-label="Hurtownia"><span class="compare-supplier-tag '+esc(row.supplier)+'">'+
    esc(name)+'</span></td>'+
    '<td data-label="Produkt"><div class="compare-product-cell">'+
      '<strong>'+esc(row.mpn||"Brak numeru MPN")+'</strong>'+
      (row.manufacturer?'<small>'+esc(row.manufacturer)+'</small>':"")+
      (row.description?'<small class="compare-description">'+esc(row.description)+'</small>':"")+
      (row.supplier_sku?'<small>SKU: '+esc(row.supplier_sku)+'</small>':"")+
      '<span class="compare-match '+(row.exact_mpn?"exact":"variant")+'">'+
      (row.exact_mpn?"Dokładny MPN":"Inny wariant / podobny numer")+'</span></div></td>'+
    '<td data-label="Dostępność"><div class="compare-stock-cell">'+compareStock(row)+'</div></td>'+
    '<td data-label="Cena za sztukę">'+comparePrice(row)+'</td>'+
    '<td data-label="Oferta">'+(link?'<a class="compare-offer-link" href="'+esc(link)+
      '" target="_blank" rel="noopener noreferrer"'+
      (row.link_kind==="catalog_search"?' title="Wyszukaj ten symbol w katalogu TME"':'')+'>'+
      (row.link_kind==="catalog_search"?'Szukaj w TME ↗':'Oferta ↗')+'</a>':'<span class="muted">—</span>')+
    '</td></tr>';
}
function renderSupplierComparison(data){
  const host=byId("compare-results");
  host.replaceChildren();
  const sources=Array.isArray(data.sources)?data.sources:[];
  const all=[];
  const sourceInfo=sources.map(source=>{
    const rows=Array.isArray(source.results)?source.results:[];
    all.push(...rows);
    const name=compareSupplierNames[source.supplier]||source.supplier;
    const count=rows.length;
    const suffix=count===1?"oferta":(count>1&&count<5?"oferty":"ofert");
    const label=compareStatusLabels[source.status]||"Status nieznany";
    return '<span class="compare-source-inline"><strong>'+esc(name)+':</strong> '+
      compareNumber(count)+' '+suffix+' <span class="compare-source-state">'+esc(label)+
      '</span></span>';
  }).join('<span class="compare-source-sep" aria-hidden="true">·</span>');
  const timestamp=Date.parse(data.checked_at);
  const when=Number.isNaN(timestamp)?"":new Date(timestamp).toLocaleString("pl-PL");
  host.innerHTML='<div class="compare-summary"><div class="compare-summary-left">'+
    '<strong>'+compareNumber(all.length)+' pozycji katalogowych</strong>'+
    (sourceInfo?'<div class="compare-summary-sources">'+sourceInfo+'</div>':"")+
    '</div><span class="muted">'+(when?'Odczyt: '+esc(when):'')+'</span></div>';
  if(all.length){
    const sorted=all.sort((a,b)=>(Number(b.exact_mpn)-Number(a.exact_mpn))||
      String(a.mpn).localeCompare(String(b.mpn),"pl")||
      String(a.supplier).localeCompare(String(b.supplier),"pl"));
    const section=document.createElement("div");
    section.className="compare-table-wrap";
    section.innerHTML='<table class="compare-table"><thead><tr>'+
      '<th>Hurtownia</th><th>Numer / producent</th><th>Dostępna ilość</th>'+
      '<th>Cena za sztukę</th><th>Link</th></tr></thead><tbody>'+
      sorted.map(compareResultRow).join("")+'</tbody></table>';
    host.append(section);
  }else{
    const empty=document.createElement("div");
    empty.className="panel compare-empty";
    const failed=sources.some(x=>x.status!=="ok");
    empty.textContent=failed?
      "Brak ofert z aktywnych źródeł. Sprawdź stan integracji w Ustawieniach lub ponów próbę.":
      "Hurtownie nie zwróciły ofert dla podanego oznaczenia.";
    host.append(empty);
  }
  const note=document.createElement("p");
  note.className="subtle-note compare-footnote";
  note.textContent=data.notice||"Ceny i ilości zależą od bieżącej odpowiedzi dostawcy.";
  host.append(note);
}
async function runSupplierComparison(event){
  event.preventDefault();
  if(!session)return;
  const form=byId("compare-search-form");
  const query=form.elements.query.value.trim();
  if(query.length<2||query.length>40){
    toast("Wpisz oznaczenie od 2 do 40 znaków.",true);return;
  }
  const run=++supplierCompareRevision;
  const button=byId("compare-search-button"),status=byId("compare-status");
  button.disabled=true;
  status.textContent="Sprawdzam dostępność i ceny w aktywnych hurtowniach…";
  byId("compare-results").replaceChildren();
  try{
    const data=await api("/api/suppliers/compare",{
      method:"POST",body:JSON.stringify({query})
    });
    if(!session||run!==supplierCompareRevision)return;
    renderSupplierComparison(data);
    const available=data.sources.filter(s=>s.status==="ok"||s.status==="partial").length;
    const found=data.sources.reduce((total,s)=>total+(s.results?.length||0),0);
    status.textContent="Zakończono sprawdzanie: "+available+" źródła, "+found+" ofert.";
  }catch(error){
    if(run!==supplierCompareRevision||!session)return;
    status.textContent="Nie udało się pobrać porównania: "+error.message;
    toast(error.message,true);
  }finally{
    if(run===supplierCompareRevision)button.disabled=false;
  }
}
document.addEventListener("DOMContentLoaded",()=>{
  byId("compare-search-form").addEventListener("submit",runSupplierComparison);
});
