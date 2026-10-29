/* Pure, testable mapping of a recognized ECU label into EXISTING Magazyn fields.
 * The scanner never commits these values: user reviews and applies each field.
 * No inference of a vehicle brand from an OEM number or ECU manufacturer.
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
    ["hardware", "hw", "Wersja HW", 160],
    ["software", "sw", "Wersja SW", 160]
  ];
  const allowed = new Set(FIELDS.map(function (f) { return f[1]; }).concat(["numbers"]));

  function text(value, max) {
    // Never concatenate the next OCR line (such as SW or S/N) into an ID.
    return (typeof value === "string" ? value : "").split(/[\r\n]/)[0]
      .replace(/[\u0000-\u001f\u007f]/g, " ").trim().slice(0, max);
  }
  function key(value) {
    return text(value, 200).toUpperCase().replace(/[^A-Z0-9]/g, "");
  }
  function lines(value) {
    return String(value || "").split(/[\n,;]+/).map(function (x) {
      return text(x, 160);
    }).filter(Boolean);
  }
  function add(list, field, label, proposed, existing) {
    const value = field === "numbers"
      ? lines(proposed).join("\n") : text(proposed, 160);
    const current = field === "numbers" ? String(existing || "").trim() : text(existing, 160);
    if (!allowed.has(field) || !value || value === current) return;
    list.push({
      field: field,
      label: label,
      value: value,
      current: current,
      selected: !current
    });
  }
  function build(scan, existing) {
    const data = scan && typeof scan === "object" ? scan : {};
    const current = existing && typeof existing === "object" ? existing : {};
    const result = [];
    const model = text(data.model, 160);
    const manufacturer = text(data.manufacturer, 160);
    // Derive designation only from fields that are visible on the label.
    const designation = text(data.designation, 160) ||
      (model ? [manufacturer, model].filter(Boolean).join(" ") : "");

    for (const [source, field, label] of FIELDS) {
      const proposed = field === "designation" ? designation : data[source];
      add(result, field, label, proposed, current[field]);
    }
    const ids = new Set([key(data.primaryNumber), key(data.serialNumber)]);
    const additions = [];
    for (const raw of Array.isArray(data.oemNumbers) ? data.oemNumbers : []) {
      const number = text(raw, 160);
      const id = key(number);
      if (!id || id.length < 7 || ids.has(id) || additions.some(x => key(x) === id)) continue;
      additions.push(number);
    }
    if (additions.length) {
      const prior = lines(current.numbers);
      const saved = new Set(prior.map(key));
      const unique = additions.filter(x => !saved.has(key(x)));
      if (unique.length) {
        const proposed = prior.concat(unique).join("\n");
        add(result, "numbers", "Dodatkowe numery OEM / zamienne", proposed, current.numbers);
      }
    }
    return result;
  }

  return {build: build, fields: FIELDS.map(x => x[1]), key: key};
});
