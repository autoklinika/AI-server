"use strict";

/* Logical catalog trees; never represents a physical warehouse location. */
let foldersCache=[];
let folderView={mode:"home",kind:"",folderId:null};

function resetFolderView(){foldersCache=[];folderView={mode:"home",kind:"",folderId:null};}
function folderChildren(kind,parentId){
  return foldersCache.filter(f=>f.kind===kind && f.parent_id===parentId)
    .sort((a,b)=>a.name.localeCompare(b.name,"pl",{sensitivity:"base"}));
}
function folderPath(id){
  const path=[],seen=new Set();
  while(id && !seen.has(id)){
    seen.add(id);
    const row=foldersCache.find(f=>f.id===id);
    if(!row)break;
    path.unshift(row);
    id=row.parent_id;
  }
  return path;
}
function folderOptions(kind,selected=null){
  let html=option("","Nieprzypisane");
  function walk(parent,depth){
    for(const f of folderChildren(kind,parent)){
      html+=option(f.id,"\u00a0\u00a0".repeat(depth)+"📁 "+f.name);
      walk(f.id,depth+1);
    }
  }
  walk(null,0);
  return html;
}
function populateFolderSelect(id,kind){
  const el=byId(id);
  if(!el)return;
  el.innerHTML=folderOptions(kind);
  if(folderView.kind===kind && folderView.mode==="folder" &&
     foldersCache.some(f=>f.id===folderView.folderId))
    el.value=String(folderView.folderId);
}
function folderFullName(id){
  return folderPath(id).map(f=>f.name).join(" / ");
}
function folderGroupName(item){
  return (item.kind==="ecu"?"Sterowniki":"Elektronika")+" / "+
    (item.folder_id?folderFullName(item.folder_id):"Nieprzypisane");
}
function folderButton(label,mode,kind,folderId,active=false,extra=""){
  const value=folderId===null?"":String(folderId);
  return '<button type="button" class="folder-nav-item '+(active?"active":"")+
    '" data-folder-mode="'+esc(mode)+'" data-folder-kind="'+esc(kind)+
    '" data-folder-id="'+esc(value)+'" '+(active?'aria-current="page"':"")+'>'+
    '<span>'+esc(label)+'</span>'+extra+'</button>';
}
function renderFolderNavigation(){
  const nav=byId("folder-navigation");
  if(!nav)return;
  let html=folderButton("Wszystkie produkty","home","",null,folderView.mode==="home");
  for(const [kind,label] of [["ecu","Sterowniki ECU"],["part","Elektronika"]]){
    html+='<div class="folder-nav-group">'+folderButton("▣ "+label,"root",kind,null,
        folderView.mode==="root"&&folderView.kind===kind);
    function walk(parent,depth){
      for(const f of folderChildren(kind,parent)){
        html+='<div class="folder-nav-indent" style="--folder-depth:'+Math.min(depth,9)+'">'+
          folderButton("📁 "+f.name,"folder",kind,f.id,
          folderView.mode==="folder"&&folderView.folderId===f.id)+'</div>';
        walk(f.id,depth+1);
      }
    }
    walk(null,1);
    html+='<div class="folder-nav-indent" style="--folder-depth:1">'+
      folderButton("Nieprzypisane","unassigned",kind,null,
       folderView.mode==="unassigned"&&folderView.kind===kind)+'</div></div>';
  }
  nav.innerHTML=html;
}
function folderTile(title,subtitle,mode,kind,id){
  return '<button type="button" class="folder-tile" data-folder-mode="'+esc(mode)+
   '" data-folder-kind="'+esc(kind)+'" data-folder-id="'+esc(id===null?"":id)+'">'+
   '<span class="folder-tile-icon" aria-hidden="true">📁</span>'+
   '<span class="folder-tile-text"><strong>'+esc(title)+'</strong><small>'+esc(subtitle)+'</small></span>'+
   '<span class="folder-tile-arrow" aria-hidden="true">›</span></button>';
}
function prepareCatalogView(results,filters){
  const searching=[...filters.entries()].some(([key,value])=>
    !["kind","limit"].includes(key)&&Boolean(value));
  const kindFilter=filters.get("kind")||"";
  if(!searching&&kindFilter!==folderView.kind){
    folderView=kindFilter?{mode:"root",kind:kindFilter,folderId:null}:
                          {mode:"home",kind:"",folderId:null};
  }
  renderFolderNavigation();
  const crumbs=byId("folder-breadcrumbs"),tiles=byId("folder-tiles"),
        count=byId("folder-scope-count");
  crumbs.replaceChildren();tiles.innerHTML="";count.textContent="";
  const breadcrumb=(label,mode,kind,id)=>
    '<button type="button" data-folder-mode="'+esc(mode)+'" data-folder-kind="'+
    esc(kind)+'" data-folder-id="'+esc(id||"")+'">'+esc(label)+'</button>';
  let html=breadcrumb("Katalog","home","",null);
  if(searching){
    crumbs.innerHTML=html+'<span> / Wyniki wyszukiwania</span>';
    count.textContent=fmt(results.length)+" znalezionych";
    const sorted=[...results].sort((a,b)=>
      folderGroupName(a).localeCompare(folderGroupName(b),"pl")||
      a.designation.localeCompare(b.designation,"pl"));
    return {items:sorted,tiles:false,grouped:true};
  }
  const unassigned=kind=>results.filter(r=>r.kind===kind&&!r.folder_id);
  if(folderView.mode==="home"){
    const all=results.length;
    tiles.innerHTML=
      folderTile("Sterowniki ECU",fmt(results.filter(r=>r.kind==="ecu").length)+" pozycji","root","ecu",null)+
      folderTile("Elektronika",fmt(results.filter(r=>r.kind==="part").length)+" pozycji","root","part",null);
    count.textContent=fmt(all)+" pozycji";
    crumbs.innerHTML=html+'<span> / Wybierz dział</span>';
    return {items:[],tiles:true,grouped:false};
  }
  const kind=folderView.kind,kindLabel=kind==="ecu"?"Sterowniki ECU":"Elektronika";
  html+='<span> / </span>'+breadcrumb(kindLabel,"root",kind,null);
  let items=[],childs=[];
  if(folderView.mode==="root"){
    childs=folderChildren(kind,null);
    tiles.innerHTML=childs.map(f=>folderTile(f.name,
      fmt(f.direct_count)+" bezpośrednio","folder",kind,f.id)).join("")+
      folderTile("Nieprzypisane",fmt(unassigned(kind).length)+" pozycji","unassigned",kind,null);
  }else if(folderView.mode==="unassigned"){
    items=unassigned(kind);
    html+='<span> / Nieprzypisane</span>';
  }else if(folderView.mode==="folder"){
    const current=foldersCache.find(f=>f.id===folderView.folderId&&f.kind===kind);
    if(!current){folderView={mode:"root",kind,folderId:null};return prepareCatalogView(results,filters);}
    const path=folderPath(current.id);
    for(const f of path){
      html+='<span> / </span>'+breadcrumb(f.name,"folder",kind,f.id);
    }
    childs=folderChildren(kind,current.id);
    tiles.innerHTML=childs.map(f=>folderTile(f.name,
      fmt(f.direct_count)+" bezpośrednio","folder",kind,f.id)).join("");
    items=results.filter(r=>r.folder_id===current.id);
  }
  crumbs.innerHTML=html;
  count.textContent=fmt(items.length)+" pozycji bezpośrednio";
  return {items,tiles:Boolean(tiles.children.length),grouped:false};
}
function navigateFolder(mode,kind,id){
  folderView={mode,kind,folderId:id};
  for(const key of ["search","filter-brand","filter-product-state","filter-tech-state","filter-location"])
    byId(key).value="";
  byId("filter-kind").value=kind;
  updateKindButtons(kind);
  loadItems();
}
async function loadFolders(){
  if(!session)return;
  try{
    foldersCache=await api("/api/folders");
    if(!session)return;
    renderFolderNavigation();
    renderFolderAdmin();
    if(!byId("page-products").hidden)loadItems();
  }catch(e){toast("Katalogi: "+e.message,true);}
}
function renderFolderAdmin(){
  if(session?.role!=="admin")return;
  const kind=byId("folder-create-kind").value;
  const select=byId("folder-create-parent"),old=select.value;
  select.innerHTML=option("","Poziom główny")+folderOptions(kind).replace(
    /^<option value="">Nieprzypisane<\/option>/,"");
  if([...select.options].some(o=>o.value===old))select.value=old;
  const list=byId("folder-admin-list");
  let html="";
  for(const [type,title] of [["ecu","Sterowniki ECU"],["part","Elektronika"]]){
    html+='<h3 class="folder-admin-heading">'+title+'</h3>';
    function walk(parent,depth){
      for(const f of folderChildren(type,parent)){
        html+='<div class="list-row folder-admin-row" style="--folder-depth:'+Math.min(depth,9)+'">'+
          '<strong>📁 '+esc(f.name)+'</strong><small class="muted">'+fmt(f.direct_count)+' poz., '+
          fmt(f.child_count)+' podkat.</small>'+
          '<span class="action-row"><button type="button" class="small" data-folder-action="rename" data-id="'+
          f.id+'">Zmień nazwę</button><button type="button" class="small" data-folder-action="delete" data-id="'+
          f.id+'">Usuń</button></span></div>';
        walk(f.id,depth+1);
      }
    }
    walk(null,0);
    if(!foldersCache.some(f=>f.kind===type))html+='<p class="subtle-note">Brak katalogów.</p>';
  }
  list.innerHTML=html;
}
function setupFolderUI(){
  byId("folder-create-kind").addEventListener("change",renderFolderAdmin);
  byId("folder-create-form").addEventListener("submit",async event=>{
    event.preventDefault();
    const form=event.currentTarget,button=form.querySelector("button[type=submit]");
    const data=Object.fromEntries(new FormData(form).entries());
    data.parent_id=Number(data.parent_id)||null;
    button.disabled=true;
    try{
      await api("/api/folders",{method:"POST",body:JSON.stringify(data)});
      form.elements.name.value="";
      toast("Utworzono katalog.");
      await loadFolders();
    }catch(e){toast(e.message,true);}
    finally{button.disabled=false;}
  });
  for(const id of ["folder-navigation","folder-tiles","folder-breadcrumbs"]){
    byId(id).addEventListener("click",event=>{
      const b=event.target.closest("[data-folder-mode]");
      if(!b)return;
      navigateFolder(b.dataset.folderMode,b.dataset.folderKind,
        Number(b.dataset.folderId)||null);
    });
  }
  byId("folder-admin-list").addEventListener("click",async event=>{
    const button=event.target.closest("[data-folder-action]");
    if(!button||session?.role!=="admin")return;
    const id=Number(button.dataset.id),folder=foldersCache.find(f=>f.id===id);
    if(!folder)return;
    try{
      if(button.dataset.folderAction==="rename"){
        const name=prompt("Nowa nazwa katalogu:",folder.name);
        if(name===null||name.trim()===folder.name)return;
        await api("/api/folders/"+id,{method:"PATCH",body:JSON.stringify({name:name.trim()})});
        toast("Zmieniono nazwę katalogu.");
      }else{
        if(!confirm("Usunąć pusty katalog „"+folder.name+"”?"))return;
        await api("/api/folders/"+id,{method:"DELETE",body:"{}"});
        toast("Usunięto katalog.");
      }
      await loadFolders();
    }catch(e){toast(e.message,true);}
  });
}
