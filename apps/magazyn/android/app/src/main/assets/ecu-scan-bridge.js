/* Injected by the Android app into the EXACT trusted Magazyn WebGUI origin.
 * No server-side files or forms are replaced. No inventory write is triggered.
 * All OCR text is displayed with textContent, never HTML interpolation.
 */
(function () {
  "use strict";
  const dialog = document.getElementById("item-dialog");
  const form = document.getElementById("item-form");
  const number = document.getElementById("new-primary-number");
  if (!dialog || !form || !number) return;
  if (document.getElementById("android-ecu-camera-row")) return;

  const label = number.closest("label");
  if (!label) return;
  const row = document.createElement("div");
  row.id = "android-ecu-camera-row";
  row.style.display = "flex";
  row.style.justifyContent = "flex-end";
  row.style.margin = "0 0 12px";
  const camera = document.createElement("button");
  camera.type = "button";
  camera.className = "secondary";
  camera.textContent = "📷  Skanuj etykietę ECU";
  camera.setAttribute("aria-label", "Odczytaj fabryczną naklejkę ECU aparatem telefonu");
  camera.style.minHeight = "46px";
  camera.style.width = "auto";
  camera.style.maxWidth = "100%";
  camera.addEventListener("click", function () {
    if (!dialog.open) return;
    // Intercepted by Android only from the trusted WebGUI main frame.
    window.location.assign("magazyn-scan://capture");
  });
  row.appendChild(camera);
  label.insertAdjacentElement("afterend", row);

  const review = document.createElement("div");
  review.id = "android-ecu-ocr-review";
  review.hidden = true;
  review.style.padding = "12px";
  review.style.margin = "0 0 12px";
  review.style.border = "1px solid #e0b08f";
  review.style.borderRadius = "10px";
  review.style.background = "#fff9f4";
  review.setAttribute("role", "status");
  review.setAttribute("aria-live", "polite");
  row.insertAdjacentElement("afterend", review);

  function appendText(node, tag, text) {
    const element = document.createElement(tag);
    element.textContent = text;
    node.appendChild(element);
    return element;
  }

  function fillWhenEmpty(name, value) {
    const input = form.elements.namedItem(name);
    if (!input || !value || String(input.value || "").trim()) return false;
    input.value = String(value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
    return true;
  }

  window.magazynApplyScan = function (json) {
    if (!dialog.open || form.elements.namedItem("kind").value !== "ecu") return;
    let scan;
    try {
      scan = JSON.parse(json);
    } catch (_) {
      return;
    }

    const filled = [];
    for (const [field, value, description] of [
      ["primary_number", scan.primaryNumber, "numer katalogowy"],
      ["manufacturer", scan.manufacturer, "producent"],
      ["hw", scan.hardware, "HW"],
      ["sw", scan.software, "SW"],
      ["model", scan.model, "model"]
    ]) {
      if (fillWhenEmpty(field, value)) filled.push(description);
    }

    if (filled.some(function (key) {
      return ["producent", "HW", "SW", "model"].includes(key);
    })) {
      const extras = form.querySelector(".form-extra");
      if (extras) extras.open = true;
    }

    review.replaceChildren();
    review.hidden = false;
    appendText(review, "strong", "Wynik odczytu etykiety");
    const description = filled.length
      ? "Uzupełniono: " + filled.join(", ") + "."
      : "Nie nadpisano istniejących pól. Sprawdź odczyt poniżej.";
    appendText(review, "p", description + " Sprawdź numery przed zapisem.");

    const candidates = Array.isArray(scan.candidates) ? scan.candidates.slice(0, 15) : [];
    if (candidates.length) {
      appendText(review, "small", "Rozpoznane numery — dotknij, aby wybrać numer główny:");
      const chips = document.createElement("div");
      chips.style.display = "flex";
      chips.style.flexWrap = "wrap";
      chips.style.gap = "6px";
      chips.style.margin = "8px 0";
      for (const candidate of candidates) {
        const chip = document.createElement("button");
        chip.type = "button";
        chip.className = "secondary small";
        chip.textContent = String(candidate).slice(0, 40);
        chip.addEventListener("click", function () {
          const existing = String(number.value || "").trim();
          if (existing && existing !== candidate &&
              !window.confirm("Zastąpić wpisany numer katalogowy wybranym odczytem?")) return;
          number.value = candidate;
          number.dispatchEvent(new Event("input", { bubbles: true }));
          number.dispatchEvent(new Event("change", { bubbles: true }));
          number.focus();
        });
        chips.appendChild(chip);
      }
      review.appendChild(chips);
    }

    if (scan.rawText || (scan.barcodes && scan.barcodes.length)) {
      const details = document.createElement("details");
      appendText(details, "summary", "Zobacz pełny tekst i kody z naklejki");
      const original = document.createElement("pre");
      original.style.whiteSpace = "pre-wrap";
      original.style.overflowWrap = "anywhere";
      original.style.fontSize = "12px";
      original.textContent = String(scan.rawText || "").slice(0, 6000) +
        (scan.barcodes && scan.barcodes.length
          ? "\n\nKODY:\n" + scan.barcodes.join("\n") : "");
      details.appendChild(original);
      review.appendChild(details);
    }
    appendText(review, "small",
      "Marka pojazdu, sprawność, ilość i lokalizacja wymagają decyzji użytkownika. " +
      "Skanowanie nie zapisuje niczego w bazie.");
  };
})();
