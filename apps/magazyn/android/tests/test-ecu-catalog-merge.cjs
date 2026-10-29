"use strict";
const assert=require("node:assert/strict");
const merge=require("../app/src/main/assets/ecu-catalog-merge.js");

const same={
  id:27,
  variant_status:"same_variant_candidate",
  matched_numbers:[
    {scan_role:"main",scanned_number:"0281016738",stored_number:"0 281 016 738"},
    {scan_role:"oem",scanned_number:"03L906022GC",stored_number:"03L 906 022 GC"}
  ],
  primary_number:"0 281 016 738",
  designation:"Bosch EDC17C46",
  manufacturer:"Bosch",brand:"DAF",brands:["DAF"],
  model:"EDC17C46",category:"ECU silnika",
  hw:"H1",sw:"S3",conflicts:[]
};

// Missing fields may be inferred from one explicitly selected catalog record,
// but MUST remain unchecked until user approves. HW/SW must NEVER be copied.
{
  const o=merge.catalogSuggestions(
    {primaryNumber:"0281016738",hardware:"",software:"",
     model:"",manufacturer:"",designation:"",vehicleBrand:""},
    {}, same
  );
  assert.deepEqual(o.map(x=>x.field),
    ["manufacturer","designation","brand","model","category"]);
  assert(o.every(x=>x.selected===false));
  assert(o.every(x=>x.confidence==="catalog"));
  assert(o.every(x=>x.source==="Magazyn #27"));
  assert.equal(o.find(x=>x.field==="model").value,"EDC17C46");
  assert.equal(o.find(x=>x.field==="category").value,"ECU silnika");
  assert(!o.some(x=>x.field==="hw"||x.field==="sw"));
}
// Existing photographed or manually entered data always takes precedence.
{
  const o=merge.catalogSuggestions(
    {primaryNumber:"0281016738",manufacturer:"Bosch",model:"EDC17C46",
     designation:"Bosch EDC17C46",vehicleBrand:"DAF",category:"EBS"},
    {brand:"DAF",hw:"H3",designation:"Moja nazwa"},same
  );
  assert.deepEqual(o,[]);
}
// Never derive a single vehicle brand from an ECU linked to multiple brands.
{
  const row={...same,brands:["DAF","MAN"]};
  const o=merge.catalogSuggestions(
    {primaryNumber:"0281016738"},{},row
  );
  assert(!o.some(x=>x.field==="brand"));
}
// A matching part number with different HW/SW is a conflict, never an
// invitation to copy another variant's fields.
{
  const row={...same,hw:"H2",sw:"S4",variant_status:"conflict",
             conflicts:["hw","sw"]};
  assert.deepEqual(merge.catalogSuggestions(
    {primaryNumber:"0281016738",hardware:"H1",software:"S3"}, {},row
  ),[]);
  assert.deepEqual(merge.conflictingFields(row),["HW","SW"]);
}
// Candidate-only number is not a strong identifier: DB suggestions require
// explicit selection from the comparison list, never blind merge.
{
  const row={...same,variant_status:"verify_variant"};
  const o=merge.catalogSuggestions(
    {primaryNumber:""},{},row
  );
  assert(o.some(x=>x.field==="primary_number"));
  assert(o.every(x=>x.selected===false));
}
console.log("ECU_CATALOG_MERGE_TESTS_PASS");
