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
  row.style.flexWrap = "wrap";
  row.style.gap = "8px";
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
  const ai = document.createElement("button");
  ai.type = "button";
  ai.className = "secondary";
  ai.textContent = "✨ AI";
  ai.setAttribute("aria-label", "Włącz AI na RTX do rozpoznawania naklejek ECU");
  ai.style.minHeight = "46px";
  ai.style.minWidth = "82px";
  ai.style.borderColor = "#B74B0D";
  row.appendChild(ai);
  row.appendChild(camera);
  label.insertAdjacentElement("afterend", row);

  const aiPanel = document.createElement("div");
  aiPanel.id = "android-ecu-ai-state";
  aiPanel.hidden = true;
  aiPanel.setAttribute("role", "status");
  aiPanel.setAttribute("aria-live", "polite");
  aiPanel.style.background = "#f5f5f4";
  aiPanel.style.borderRadius = "10px";
  aiPanel.style.padding = "10px 12px";
  aiPanel.style.marginBottom = "12px";
  const aiStatus = document.createElement("div");
  aiStatus.style.fontSize = "13px";
  aiStatus.style.fontWeight = "600";
  const aiBar = document.createElement("progress");
  aiBar.max = 100;
  aiBar.value = 0;
  aiBar.style.width = "100%";
  aiBar.style.height = "12px";
  aiBar.style.accentColor = "#B74B0D";
  aiBar.style.marginTop = "8px";
  aiPanel.append(aiStatus, aiBar);
  row.insertAdjacentElement("afterend", aiPanel);

  let aiReady = false;
  let aiSessionId = "";
  let aiPhase = "off";
  let aiTimer = null;
  let aiActionBusy = false;

  function loadingPhase(phase) {
    return ["checking", "reserving", "loading", "warming", "closing", "scanning"].includes(phase);
  }

  function paintAi(status) {
    const state = status || {};
    aiPhase = String(state.phase || "off");
    aiReady = state.ready === true && Boolean(state.session_id);
    aiSessionId = aiReady ? String(state.session_id) : (
      loadingPhase(aiPhase) ? String(state.session_id || "") : ""
    );
    const starting = loadingPhase(aiPhase);
    const text = String(state.message || (aiReady ? "RTX gotowy" : "Aparat używa OCR telefonu."));
    aiPanel.hidden = aiPhase === "off";
    aiStatus.textContent = text;
    aiBar.hidden = !starting && !aiReady;
    aiBar.value = Math.max(0, Math.min(100, Number(state.progress) || 0));
    ai.textContent = aiReady ? "✨ AI ✓" : (starting ? "✨ AI…" : "✨ AI");
    ai.style.backgroundColor = aiReady ? "#e9f7ec" : "";
    ai.style.borderColor = aiReady ? "#288044" : "#B74B0D";
    ai.disabled = aiActionBusy || starting;
    ai.setAttribute("aria-pressed", aiReady ? "true" : "false");
    camera.title = aiReady ? "Zrób zdjęcie — rozpoznanie przez RTX" :
      "Zrób zdjęcie — lokalny OCR telefonu";
  }

  function planPoll(delay) {
    clearTimeout(aiTimer);
    if (!dialog.open) return;
    aiTimer = setTimeout(pollAi, delay);
  }

  async function pollAi() {
    if (!dialog.open) return;
    try {
      const status = await api("/api/ecu-label/status");
      paintAi(status);
      if (loadingPhase(aiPhase) || aiReady) {
        planPoll(aiReady ? 4000 : 1200);
      }
    } catch (_) {
      paintAi({ phase: "error", message: "Brak połączenia z AI. Aparat używa OCR." });
    }
  }

  ai.addEventListener("click", async function () {
    if (!dialog.open || aiActionBusy) return;
    aiActionBusy = true;
    ai.disabled = true;
    try {
      if (aiReady && aiSessionId) {
        const result = await api("/api/ecu-label/deactivate", {
          method: "POST", body: JSON.stringify({ session_id: aiSessionId })
        });
        paintAi(result);
      } else {
        const result = await api("/api/ecu-label/activate", {
          method: "POST", body: JSON.stringify({ mapping_version: 2 })
        });
        paintAi(result);
        planPoll(1000);
      }
    } catch (error) {
      const text = error instanceof Error ? error.message : "RTX niedostępny";
      paintAi({ phase: "busy", message: text + " Aparat pozostaje w trybie OCR." });
    } finally {
      aiActionBusy = false;
      ai.disabled = loadingPhase(aiPhase);
    }
  });

  dialog.addEventListener("close", function () {
    clearTimeout(aiTimer);
    scanRevision++;
    reviewPending = false;
    scanProcessing = false;
    hideFooter(false);
    if (typeof review !== "undefined") { review.hidden = true; review.replaceChildren(); }
    // Release an idle ready RTX reservation immediately on leaving the form.
    // If loading/scanning is still running, the backend's bounded TTL cleans up.
    const sid = aiReady ? aiSessionId : "";
    aiReady = false;
    aiSessionId = "";
    paintAi({ phase: "off" });
    if (sid) {
      api("/api/ecu-label/deactivate", {
        method: "POST", body: JSON.stringify({ session_id: sid })
      }).catch(function () { /* TTL is the fail-safe */ });
    }
  });

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
  aiPanel.insertAdjacentElement("afterend", review);

  function appendText(node, tag, text) {
    const element = document.createElement(tag);
    element.textContent = text;
    node.appendChild(element);
    return element;
  }

  let reviewPending = false;
  const footer = form.querySelector(".sticky-actions");
  function hideFooter(hide) {
    // The usual Save/Cancel bar obscures long OCR controls on Android.
    // Hide it during review. It reappears after Apply/Discard or dialog close.
    if (footer) footer.style.display = hide ? "none" : "";
  }
  let scanProcessing = false;
  let scanRevision = 0;

  // The user must explicitly apply the interpreted values. A correct OCR
  // transcript never authorizes silently overwriting form fields or saving.
  form.addEventListener("submit", function (event) {
    if (!reviewPending && !scanProcessing) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    if (typeof toast === "function") {
      toast("Najpierw sprawdź wynik skanowania i wybierz Zastosuj lub Odrzuć.", true);
    }
    review.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, true);

  function currentFormValues() {
    const result = {};
    for (const field of ["primary_number", "manufacturer", "designation",
                          "brand", "model", "category", "hw", "sw", "numbers", "notes"]) {
      const input = form.elements.namedItem(field);
      result[field] = input ? String(input.value || "") : "";
    }
    return result;
  }

  function createEditor(suggestion, container) {
    const line = document.createElement("div");
    line.dataset.ecuField = suggestion.field;
    line.style.padding = "9px 0";
    line.style.borderBottom = "1px solid #e5d5cb";

    const label = document.createElement("label");
    label.style.display = "flex";
    label.style.alignItems = "center";
    label.style.gap = "8px";
    label.style.fontWeight = "600";
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = Boolean(suggestion.selected);
    checkbox.style.width = "20px";
    checkbox.style.height = "20px";
    checkbox.setAttribute("aria-label", "Zastosuj: " + suggestion.label);
    const name = document.createElement("span");
    name.textContent = suggestion.label;
    label.append(checkbox, name);
    const editor = document.createElement(
      ["numbers","notes"].includes(suggestion.field) ? "textarea" : "input"
    );
    if (!["numbers","notes"].includes(suggestion.field)) editor.type = "text";
    else editor.rows = suggestion.field === "notes" ? 4 : 3;
    editor.value = String(suggestion.value || "");
    editor.maxLength = suggestion.field === "notes" ? 1800
      : suggestion.field === "numbers" ? 1500 : 160;
    editor.setAttribute("aria-label", "Rozpoznano: " + suggestion.label);
    editor.style.width = "100%";
    editor.style.marginTop = "6px";
    editor.addEventListener("input", function () {
      checkbox.checked = true;
    });
    line.append(label, editor);
    if (suggestion.confidence === "suggestion") {
      const caution = appendText(line, "small",
        "Sugestia AI — sprawdź przypisanie; domyślnie niezatwierdzona.");
      caution.style.color = "#9a562d";
      caution.style.display = "block";
    }
    if (suggestion.field === "notes") {
      const caveat = appendText(line, "small",
        "Numer seryjny dotyczy egzemplarza, a nie wszystkich sztuk tego typu.");
      caveat.style.display = "block";
    }
    if (suggestion.current) {
      const prior = appendText(line, "small",
        "Obecnie w formularzu: " + String(suggestion.current).slice(0, 180));
      prior.style.display = "block";
      prior.style.marginTop = "3px";
      prior.style.color = "#7d3b1b";
      appendText(line, "small",
        "Zastąpienie wymaga zaznaczenia pola; domyślnie jest wyłączone.");
    }
    container.appendChild(line);
    return line;
  }

  window.magazynApplyScan = function (json) {
    if (!dialog.open || form.elements.namedItem("kind").value !== "ecu") return;
    let scan;
    try { scan = JSON.parse(json); } catch (_) { return; }
    if (!scan || typeof scan !== "object") return;
    const mapper = window.magazynEcuFormMap;
    if (!mapper || typeof mapper.build !== "function") {
      if (typeof toast === "function") toast("Moduł mapowania ECU jest niedostępny.", true);
      return;
    }

    const items = mapper.build(scan, currentFormValues());
    reviewPending = true;
    hideFooter(true);
    review.replaceChildren();
    review.hidden = false;
    appendText(review, "strong", "Sprawdź przypisanie danych z naklejki");
    appendText(review, "p",
      "To są propozycje, a nie zapis. Zaznacz pola, które chcesz przenieść do formularza.");
    const source = scan.engine === "server_vision_ocr"
      ? "AI RTX + OCR telefonu" : "OCR telefonu";
    appendText(review, "small", "Odczyt: " + source);

    for (const warning of Array.isArray(scan.warnings) ? scan.warnings.slice(0, 8) : []) {
      const p = appendText(review, "p", "⚠ " + String(warning).slice(0, 250));
      p.style.color = "#a53b19";
    }

    const candidates = Array.isArray(scan.candidates)
      ? scan.candidates.slice(0, 15) : [];
    const editors = document.createElement("div");
    editors.id = "ecu-scan-field-suggestions";
    for (const suggestion of items) createEditor(suggestion, editors);

    if (candidates.length) {
      appendText(review, "small",
        "Numery wykryte na etykiecie. Wybierz numer główny, jeśli przypisanie jest niepewne:");
      const chips = document.createElement("div");
      chips.style.display = "flex";
      chips.style.flexWrap = "wrap";
      chips.style.gap = "6px";
      chips.style.margin = "7px 0";
      for (const value of candidates) {
        const chip = document.createElement("button");
        chip.type = "button";
        chip.className = "secondary small";
        chip.textContent = String(value).slice(0, 40);
        chip.addEventListener("click", function () {
          let editor = Array.from(editors.children)
            .find(el => el.dataset.ecuField === "primary_number");
          if (!editor) {
            const current = currentFormValues().primary_number;
            const slot = createEditor({
              field: "primary_number", label: "Numer katalogowy / OEM",
              value: value, current: current, selected: true
            }, editors);
            editors.prepend(slot);
            editor = slot;
          }
          const field = editor.querySelector("input[type=text]");
          if (field) {
            field.value = String(value).slice(0, 160);
            field.dispatchEvent(new Event("input", { bubbles: true }));
          }
        });
        chips.appendChild(chip);
      }
      review.appendChild(chips);
    }

    review.appendChild(editors);
    const otherNumbers = typeof mapper.extraNumbers === "function"
      ? mapper.extraNumbers(scan) : [];
    if (otherNumbers.length) {
      const group = document.createElement("div");
      group.id = "ecu-extra-unclassified-numbers";
      group.style.margin = "12px 0";
      appendText(group, "strong", "Dodatkowe oznaczenia odnalezione przez AI");
      appendText(group, "p",
        "Te numery są na etykiecie, ale ich rola nie jest pewna. " +
        "Dodaj je do numerów zamiennych tylko po sprawdzeniu.");
      for (const item of otherNumbers) {
        const itemRow = document.createElement("div");
        itemRow.style.display = "flex";
        itemRow.style.alignItems = "center";
        itemRow.style.flexWrap = "wrap";
        itemRow.style.gap = "8px";
        itemRow.style.margin = "6px 0";
        const role = item.role === "oem" ? "Możliwy OEM"
          : item.role === "supplier" ? "Numer producenta ECU"
          : "Nieokreślony numer";
        appendText(itemRow, "span", item.value + " · " + role);
        const addNumber = document.createElement("button");
        addNumber.type = "button";
        addNumber.className = "secondary small";
        addNumber.textContent = "+ Dodaj do numerów dodatkowych";
        addNumber.addEventListener("click", function () {
          let editor = Array.from(editors.children)
            .find(el => el.dataset.ecuField === "numbers");
          if (!editor) {
            editor = createEditor({
              field: "numbers", label: "Dodatkowe numery OEM / zamienne",
              value: currentFormValues().numbers || item.value,
              current: currentFormValues().numbers, selected: true,
              confidence: "suggestion"
            }, editors);
          }
          const field = editor.querySelector("textarea");
          const check = editor.querySelector("input[type=checkbox]");
          if (field && check) {
            field.value = mapper.appendNumber(field.value,item.value,
              scan.primaryNumber,scan.serialNumber);
            check.checked = true;
            addNumber.disabled = true;
            addNumber.textContent = "Dodano do podglądu";
          }
        });
        itemRow.appendChild(addNumber);
        group.appendChild(itemRow);
      }
      // Keep uncertain-number controls BEFORE the long field list, so
      // Magazyn's fixed bottom Save bar does not cover them on Android.
      group.style.scrollMarginBottom = "160px";
      review.insertBefore(group, editors);
    }
    if (!items.length && !candidates.length && !otherNumbers.length) {
      appendText(review, "p",
        "Nie udało się jednoznacznie przypisać numerów. Wpisz dane ręcznie.");
    }

    const details = document.createElement("details");
    details.style.marginTop = "12px";
    appendText(details, "summary", "Pokaż oryginalny odczyt AI i OCR telefonu");
    const raw = document.createElement("pre");
    raw.style.whiteSpace = "pre-wrap";
    raw.style.overflowWrap = "anywhere";
    raw.style.fontSize = "12px";
    raw.textContent = "AI:\n" + String(scan.rawText || "").slice(0, 6000) +
      "\n\nOCR telefonu:\n" + String(scan.phoneText || "").slice(0, 6000) +
      "\n\nKody:\n" + (Array.isArray(scan.barcodes) ? scan.barcodes.slice(0, 12).join("\n") : "");
    details.appendChild(raw);
    review.appendChild(details);

    appendText(review, "small",
      "Marka pojazdu jest proponowana tylko wtedy, gdy widnieje na etykiecie. " +
      "Numer seryjny nie jest numerem zamiennym. Stan, ilość i lokalizację wybierz ręcznie.");
    if (scan.serialNumber) appendText(review, "small",
      "Numer seryjny (informacyjnie): " + String(scan.serialNumber).slice(0, 60));

    const controls = document.createElement("div");
    controls.style.display = "flex";
    controls.style.flexWrap = "wrap";
    controls.style.gap = "8px";
    controls.style.marginTop = "12px";
    const apply = document.createElement("button");
    apply.type = "button";
    apply.className = "primary";
    apply.textContent = "Zastosuj zaznaczone pola";
    const dismiss = document.createElement("button");
    dismiss.type = "button";
    dismiss.className = "secondary";
    dismiss.textContent = "Odrzuć odczyt";
    apply.addEventListener("click", function () {
      let updated = 0;
      const approvedFields = new Set(mapper.fields);
      for (const row of Array.from(editors.children)) {
        const fieldName = row.dataset.ecuField;
        if (!approvedFields.has(fieldName)
            && fieldName !== "numbers" && fieldName !== "notes") continue;
        const checked = row.querySelector("input[type=checkbox]");
        const entry = row.querySelector("input[type=text],textarea");
        const target = form.elements.namedItem(fieldName);
        if (!checked || !checked.checked || !target || !entry) continue;
        const value = String(entry.value || "").trim();
        if (!value || target.value === value) continue;
        target.value = value;
        target.dispatchEvent(new Event("input", { bubbles: true }));
        target.dispatchEvent(new Event("change", { bubbles: true }));
        updated++;
      }
      reviewPending = false;
      hideFooter(false);
      review.replaceChildren();
      appendText(review, "strong", "Dane zastosowane do formularza");
      appendText(review, "p", updated
        ? "Przeniesiono " + updated + " pól. Sprawdź je przed zapisem."
        : "Nie przeniesiono żadnego pola. Uzupełnij dane ręcznie.");
      if (typeof scheduleSimilarCheck === "function") scheduleSimilarCheck();
    });
    dismiss.addEventListener("click", function () {
      reviewPending = false;
      hideFooter(false);
      review.hidden = true;
      review.replaceChildren();
    });
    controls.append(apply, dismiss);
    // Keep approval visible at the TOP of the preview, away from Magazyn's
    // sticky bottom save-bar on narrow Android screens.
    review.insertBefore(controls, review.children[2] || null);
    review.style.paddingBottom = "92px";
    review.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  window.magazynRequestAiScan = async function (json) {
    if (!dialog.open || form.elements.namedItem("kind").value !== "ecu") return;
    let local;
    try { local = JSON.parse(json); } catch (_) { return; }
    const revision = ++scanRevision;
    const jpeg = String(local.jpegBase64 || "");
    delete local.jpegBase64; // Never show/store full image bytes in UI state.
    if (!aiReady || !aiSessionId || !jpeg || typeof api !== "function") {
      local.phoneText = String(local.rawText || "");
      window.magazynApplyScan(JSON.stringify(local));
      appendText(review, "small", "Użyto OCR telefonu — dane wymagają zatwierdzenia.");
      return;
    }

    scanProcessing = true;
    reviewPending = false;
    hideFooter(true);
    review.replaceChildren();
    review.hidden = false;
    appendText(review, "p", "Analizuję etykietę na RTX 5060 Ti…");
    camera.disabled = true;
    const submit = document.getElementById("item-submit");
    const originalSubmitDisabled = submit ? submit.disabled : true;
    if (submit) submit.disabled = true;
    try {
      // API requires an authenticated session, CSRF and an active RTX lease.
      const analyzed = await api("/api/ecu-label/analyze", {
        method: "POST",
        body: JSON.stringify({
          session_id: aiSessionId,
          mapping_version: 2,
          photo_base64: jpeg,
          local_text: String(local.rawText || "").slice(0, 6000),
          barcodes: (Array.isArray(local.barcodes) ? local.barcodes : [])
            .slice(0, 12).map(x => String(x).slice(0, 160))
        })
      });
      if (!dialog.open || revision !== scanRevision) return;
      scanProcessing = false;
      window.magazynApplyScan(JSON.stringify(analyzed));
    } catch (error) {
      if (!dialog.open || revision !== scanRevision) return;
      scanProcessing = false;
      local.phoneText = String(local.rawText || "");
      window.magazynApplyScan(JSON.stringify(local));
      aiReady = false;
      aiSessionId = "";
      paintAi({phase: "error", message: "Tryb RTX przerwany lub wygasł. Aparat używa OCR telefonu."});
      appendText(review, "p",
        "AI jest niedostępne; pokazano propozycje OCR telefonu. " +
        "Sprawdź każdą cyfrę przed zastosowaniem.");
    } finally {
      if (revision === scanRevision) {
        scanProcessing = false;
        camera.disabled = false;
        if (submit && dialog.open) {
          // Preserve the server's existing duplicate-variant guard.
          if (typeof renderSimilar === "function") renderSimilar();
          else submit.disabled = originalSubmitDisabled;
        }
      }
    }
  };
})();
