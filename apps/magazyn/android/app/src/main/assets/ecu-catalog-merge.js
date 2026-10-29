/* Safe catalog-based proposals, separate from OCR and database matching.
 * DB metadata is only proposed if the user selects a stored ECU; optical
 * evidence always wins. NEVER copy HW/SW or serial as if photographed.
 */
(function(root,factory) {
  "use strict";
  const matcher=factory();
  if(typeof module==="object" && module.exports) module.exports=matcher;
  if(root) root.magazynEcuCatalogMerge=matcher;
})(typeof window!=="undefined"?window:globalThis,function() {
  "use strict";
  const LABELS={
    primary_number:"Numer katalogowy / OEM",
    manufacturer:"Producent sterownika",
    designation:"Nazwa lub oznaczenie produktu",
    brand:"Marka pojazdu",
    model:"Typ / model ECU",
    category:"Zastosowanie / rodzaj ECU",
  };
  const allowed=new Set(Object.keys(LABELS));

  function text(value,max=160) {
    return (typeof value==="string"?value:"").split(/[\r\n]/)[0]
      .replace(/[\u0000-\u001f\u007f]/g," ").trim().slice(0,max);
  }
  function key(v) {
    return text(v).toUpperCase().replace(/[^A-Z0-9]/g,"");
  }

  function catalogSuggestions(scan,form,row) {
    if(!row || typeof row!=="object")return [];
    if(row.variant_status==="conflict" || !Array.isArray(row.matched_numbers)
       || !row.matched_numbers.length)return [];
    const scanned=scan&&typeof scan==="object"?scan:{};
    const current=form&&typeof form==="object"?form:{};
    const brandValues=Array.from(new Set(
      [row.brand,...(Array.isArray(row.brands)?row.brands:[])].map(key).filter(Boolean)
    ));
    const brand=brandValues.length===1?text(row.brand||row.brands?.[0]):"";
    const sources=[
      ["primary_number","primaryNumber",row.primary_number],
      ["manufacturer","manufacturer",row.manufacturer],
      ["designation","designation",row.designation],
      ["brand","vehicleBrand",brand],
      ["model","model",row.model],
      ["category","category",row.category],
    ];
    const result=[];
    for(const [field,src,value] of sources){
      if(!allowed.has(field))continue;
      // Do not contradict photographed evidence or manually filled fields.
      if(text(scanned[src]) || text(current[field]))continue;
      const proposed=text(value);
      if(!proposed)continue;
      result.push({
        field,label:LABELS[field],value:proposed,
        current:"", selected:false, confidence:"catalog",
        source:"Magazyn #"+String(row.id),
      });
    }
    return result;
  }

  function conflictingFields(row) {
    const names={hw:"HW",sw:"SW",model:"Typ ECU",
      manufacturer:"Producent ECU",brand:"Marka pojazdu"};
    return (Array.isArray(row?.conflicts)?row.conflicts:[])
      .map(v=>names[v]||text(v,30));
  }
  return {catalogSuggestions,conflictingFields,key};
});
