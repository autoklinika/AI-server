/* Map evidence-grounded ECU label data into the EXISTING Magazyn form.
 * All changes are suggestions until the operator explicitly presses Apply.
 * Low-confidence AI classification is UNSELECTED by default.
 */
(function (root, factory) {
  "use strict";
  const mapper = factory();
  if (typeof module === "object" && module.exports) module.exports = mapper;
  if (root) root.magazynEcuFormMap = mapper;
})(typeof window !== "undefined" ? window : globalThis, function () {
  "use strict";

  const FIELDS = [
    ["primaryNumber", "primary_number", "Numer katalogowy / OEM", 160],
    ["manufacturer", "manufacturer", "Producent sterownika", 160],
    ["designation", "designation", "Nazwa lub oznaczenie produktu", 160],
    ["vehicleBrand", "brand", "Marka pojazdu", 100],
    ["model", "model", "Typ / model ECU", 160],
    ["category", "category", "Zastosowanie / rodzaj ECU", 160],
    ["hardware", "hw", "Wersja HW", 160],
    ["software", "sw", "Wersja SW", 160]
  ];
  const allowed = new Set(FIELDS.map(x => x[1]).concat(["numbers","notes"]));

  function text(value, max) {
    return (typeof value === "string" ? value : "").split(/[\r\n]/)[0]
      .replace(/[\u0000-\u001f\u007f]/g, " ").trim().slice(0, max);
  }

  function key(value) {
    return text(value, 200).toUpperCase().replace(/[^A-Z0-9]/g, "");
  }

  function lines(value) {
    return String(value || "").split(/[\n,;]+/).map(x => text(x, 160)).filter(Boolean);
  }

  function multiline(value, max) {
    return String(value || "").split(/\r?\n/).map(x => text(x, 180))
      .filter(Boolean).join("\n").slice(0, max);
  }

  function add(result, field, label, proposed, existing, confidence = "verified") {
    if (!allowed.has(field)) return;
    const value = field === "notes" ? multiline(proposed, 1800)
      : field === "numbers" ? lines(proposed).join("\n") : text(proposed, 160);
    const current = field === "notes" ? multiline(existing, 1800)
      : field === "numbers" ? lines(existing).join("\n") : text(existing, 160);
    if (!value || value === current) return;
    result.push({
      field, label, value, current, confidence,
      selected: !current && confidence === "verified"
    });
  }

  function appendNumber(previous, candidate, primary, serial) {
    const input = lines(previous);
    const number = text(candidate, 160);
    const id = key(number);
    if (!id || id.length < 7 || [key(primary),key(serial)].includes(id)) {
      return input.join("\n");
    }
    if (input.some(x => key(x) === id)) return input.join("\n");
    return input.concat([number]).join("\n");
  }

  function build(scan, existing) {
    const data = scan && typeof scan === "object" ? scan : {};
    const current = existing && typeof existing === "object" ? existing : {};
    const confidence = data.fieldConfidence && typeof data.fieldConfidence === "object"
      ? data.fieldConfidence : {};
    const result = [];
    const model = text(data.model, 160);
    const maker = text(data.manufacturer, 160);
    const designation = text(data.designation, 160) ||
      (model ? [maker,model].filter(Boolean).join(" ") : "");

    for (const [source,field,label] of FIELDS) {
      const value = field === "designation" ? designation : data[source];
      add(result,field,label,value,current[field],
        confidence[field] === "suggestion" ? "suggestion" : "verified");
    }

    const ids = new Set([key(data.primaryNumber), key(data.serialNumber)]);
    let proposedNumbers = lines(current.numbers).join("\n");
    const original = proposedNumbers;
    for (const raw of Array.isArray(data.oemNumbers) ? data.oemNumbers : []) {
      const number = text(raw, 160);
      if (ids.has(key(number))) continue;
      proposedNumbers = appendNumber(proposedNumbers,number,
        data.primaryNumber,data.serialNumber);
    }
    if (proposedNumbers !== original) {
      add(result,"numbers","Dodatkowe numery OEM / zamienne",
          proposedNumbers,current.numbers);
    }

    // Serial numbers are PER-ECU details, while Magazyn catalog is quantity-based.
    // Offer notes only as an opt-in; do not silently associate one S/N to all units.
    const annotations = [];
    if (text(data.serialNumber, 60)) {
      annotations.push("S/N: " + text(data.serialNumber, 60));
    }
    if (text(data.productionDate, 60)) {
      annotations.push("Data produkcji: " + text(data.productionDate, 60));
    }
    if (annotations.length) {
      const before = multiline(current.notes, 1800);
      const currentLines = new Set(before.split("\n").map(x => x.trim().toUpperCase()));
      const newLines = annotations.filter(x => !currentLines.has(x.toUpperCase()));
      const proposed = [before,...newLines].filter(Boolean).join("\n");
      if (newLines.length) add(result,"notes",
        "Uwagi — numer seryjny / data (tylko dla tego egzemplarza)",
        proposed,current.notes,"suggestion");
    }
    return result;
  }

  function extraNumbers(scan) {
    const data = scan && typeof scan === "object" ? scan : {};
    const protectedNumbers = new Set([
      key(data.primaryNumber),key(data.serialNumber),
      key(data.hardware),key(data.software)
    ]);
    const oemSet = new Set((Array.isArray(data.oemNumbers)
      ? data.oemNumbers : []).map(key));
    const dedup = new Set();
    const output = [];
    for (const item of Array.isArray(data.extraNumbers) ? data.extraNumbers.slice(0,20) : []) {
      if (!item || typeof item !== "object") continue;
      const value = text(item.value, 160);
      const id = key(value);
      if (!id || id.length < 7 || protectedNumbers.has(id)
        || oemSet.has(id) || dedup.has(id)) continue;
      dedup.add(id);
      output.push({ value, role: ["oem","supplier"].includes(item.role)
        ? item.role : "unclassified", confidence: "suggestion" });
    }
    return output;
  }

  return {build,fields:FIELDS.map(x=>x[1]),key,appendNumber,extraNumbers};
});
