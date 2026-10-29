"use strict";
const assert = require("node:assert/strict");
const mapper = require("../app/src/main/assets/ecu-form-mapping.js");

function proposed(scan, current = {}) {
  return Object.fromEntries(mapper.build(scan, current).map(x => [x.field, x]));
}

// Exact target fields: no direct, untyped writes from an OCR transcript.
{
  const x = proposed({
    manufacturer: "Bosch", primaryNumber: "0281016738",
    model: "EDC17C46", designation: "Bosch EDC17C46",
    hardware: "H1", software: "S3", vehicleBrand: "",
    serialNumber: "987654321", oemNumbers: ["03L906022GC"]
  });
  assert.equal(x.primary_number.value, "0281016738");
  assert.equal(x.designation.value, "Bosch EDC17C46");
  assert.equal(x.manufacturer.value, "Bosch");
  assert.equal(x.model.value, "EDC17C46");
  assert.equal(x.hw.value, "H1");
  assert.equal(x.sw.value, "S3");
  assert.equal(x.numbers.value, "03L906022GC");
  assert.equal(x.brand, undefined);       // No inference from Bosch/OEM.
  assert.equal(x.serial_number, undefined); // No serial field in inventory.
  for (const field of Object.keys(x)) {
    assert.equal(x[field].selected, field !== "notes");
  }
}

// Previously entered data is protected; offer a visible, opt-in replacement.
{
  const x = proposed(
    {primaryNumber:"0281016738",hardware:"H2",designation:"Bosch EDC17C46"},
    {primary_number:"0281016739",hw:"H1",designation:"My manual label"}
  );
  assert.equal(x.primary_number.selected, false);
  assert.equal(x.primary_number.current, "0281016739");
  assert.equal(x.hw.selected, false);
  assert.equal(x.designation.selected, false);
}

// OEM aliases only from structured OEM fields, not serials and raw codes.
{
  const x = proposed(
    {primaryNumber:"0281016738",serialNumber:"987654321",
     oemNumbers:["03L 906 022 GC","0281016738","987654321","03L-906-022-GC","03L906023GC"]},
    {numbers:"AA1234567"}
  );
  assert.equal(x.numbers.value,"AA1234567\n03L 906 022 GC\n03L906023GC");
  assert.equal(x.numbers.selected,false);
}

// Never write fabricated names where the label has no ECU type.
{
  const x = proposed({manufacturer:"Bosch",model:"",designation:""});
  assert.equal(x.designation, undefined);
}
// If manufacturer and model are both transcribed, derive a human-readable name.
{
  const x = proposed({manufacturer:"Continental",model:"SID807",designation:""});
  assert.equal(x.designation.value,"Continental SID807");
}

// Explicit brand can be proposed, but current value stays untouched unless selected.
{
  const x = proposed({vehicleBrand:"DAF"},{brand:"MAN"});
  assert.equal(x.brand.value,"DAF");
  assert.equal(x.brand.selected,false);
}

// Reject content from unlabeled OCR, unknown target keys and HTML injection attempts.
{
  const x = proposed({serialNumber:"987654321",unknownApiField:"not allowed",
                      primaryNumber:"0281016738\nSW: 999"});
  assert.equal(x.unknownApiField,undefined);
  assert.equal(x.primary_number.value,"0281016738");
  assert.deepEqual(Object.keys(x),["primary_number","notes"]);
  assert.equal(x.notes.selected,false);
}



// Full ECU inventory coverage: functional category plus serial/date notes.
{
  const x = proposed({
    manufacturer:"Continental", primaryNumber:"A2C12345678",
    model:"SID807EVO", designation:"Continental SID807EVO",
    vehicleBrand:"DAF", category:"ECU silnika",
    hardware:"H22",software:"22.1",serialNumber:"SN9823456",
    productionDate:"2024-06-17",
    oemNumbers:["1862828"],
    fieldConfidence:{category:"suggestion",primary_number:"suggestion"}
  });
  assert.equal(x.designation.value,"Continental SID807EVO");
  assert.equal(x.category.value,"ECU silnika");
  assert.equal(x.category.selected,false);
  assert.equal(x.primary_number.selected,false);
  assert.equal(x.primary_number.confidence,"suggestion");
  assert.equal(x.notes.value,"S/N: SN9823456\nData produkcji: 2024-06-17");
  assert.equal(x.notes.selected,false);
  assert.equal(x.numbers.value,"1862828");
  assert.equal(x.numbers.selected,true);
}

// Extra identifiers remain suggestions until the user manually classifies them.
{
  const data={
    primaryNumber:"0281016738",serialNumber:"987654321",hardware:"H1",software:"S3",
    oemNumbers:["03L906022GC"],
    extraNumbers:[
      {value:"A2C12345678",role:"supplier"},
      {value:"987654321",role:"oem"},
      {value:"03L906022GC",role:"oem"},
      {value:"A2C-12345678",role:"unclassified"},
      {value:"5WK96745",role:"unclassified"}
    ]
  };
  assert.deepEqual(mapper.extraNumbers(data),[
    {value:"A2C12345678",role:"supplier",confidence:"suggestion"},
    {value:"5WK96745",role:"unclassified",confidence:"suggestion"}
  ]);
  assert.equal(mapper.appendNumber("03L906022GC","5WK96745",
                                   data.primaryNumber,data.serialNumber),
               "03L906022GC\n5WK96745");
  assert.equal(mapper.appendNumber("03L906022GC","987654321",
                                   data.primaryNumber,data.serialNumber),"03L906022GC");
}

// Never implicitly write a serial number into a quantity-based catalog record.
{
  const x = proposed({serialNumber:"ABC12345678",productionDate:"2024-04-07"},
                     {notes:"Ocena techniczna do wykonania"});
  assert.equal(x.notes.selected,false);
  assert.equal(x.notes.value,
               "Ocena techniczna do wykonania\nS/N: ABC12345678\nData produkcji: 2024-04-07");
}

console.log("ECU_FORM_MAPPING_TESTS_PASS");
