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
          method: "POST", body: JSON.stringify({})
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

  window.magazynRequestAiScan = async function (json) {
    if (!dialog.open || form.elements.namedItem("kind").value !== "ecu") return;
    let local;
    try { local = JSON.parse(json); } catch (_) { return; }
    const jpeg = String(local.jpegBase64 || "");
    delete local.jpegBase64; // Never show or keep image bytes in UI state.
    if (!aiReady || !aiSessionId || !jpeg || typeof api !== "function") {
      window.magazynApplyScan(JSON.stringify(local));
      appendText(review, "small", "Odczyt OCR telefonu. Aby włączyć RTX, naciśnij ikonę AI przed skanowaniem.");
      return;
    }

    review.replaceChildren();
    review.hidden = false;
    appendText(review, "p", "Analizuję etykietę na RTX 5060 Ti…");
    camera.disabled = true;
    const submit = document.getElementById("item-submit");
    const originalSubmitDisabled = submit ? submit.disabled : true;
    if (submit) submit.disabled = true;
    try {
      // API uses existing authenticated session and X-CSRF-Token.
      // The URL is relative, so the photo cannot leave the trusted Magazyn origin.
      const analyzed = await api("/api/ecu-label/analyze", {
        method: "POST",
        body: JSON.stringify({
          session_id: aiSessionId,
          photo_base64: jpeg,
          local_text: String(local.rawText || "").slice(0, 6000),
          barcodes: (Array.isArray(local.barcodes) ? local.barcodes : [])
            .slice(0, 12).map(x => String(x).slice(0, 160))
        })
      });
      if (!dialog.open) return;
      window.magazynApplyScan(JSON.stringify(analyzed));
      const prefix = analyzed.engine === "server_vision_ocr"
        ? "RTX 5060 Ti + OCR Android"
        : "OCR Android";
      appendText(review, "p", "Źródło: " + prefix + ". Numery sprawdź z naklejką.");
      if (analyzed.serialNumber) {
        appendText(review, "p",
          "Numer seryjny (informacyjnie): " + String(analyzed.serialNumber).slice(0, 50));
      }
      for (const warning of (Array.isArray(analyzed.warnings) ? analyzed.warnings : []).slice(0, 8)) {
        appendText(review, "p", "⚠ " + String(warning).slice(0, 250));
      }
    } catch (error) {
      if (!dialog.open) return;
      window.magazynApplyScan(JSON.stringify(local));
      aiReady = false;
      aiSessionId = "";
      paintAi({phase: "error", message: "Tryb RTX przerwany lub wygasł. Aparat używa OCR telefonu."});
      appendText(review, "p",
        "RTX jest niedostępny lub sesja AI wygasła. Użyto OCR telefonu. " +
        "Sprawdź ręcznie wszystkie numery przed dodaniem ECU.");
    } finally {
      camera.disabled = false;
      if (submit && dialog.open) {
        // Let the original Magazyn duplicate/variant validation determine state.
        if (typeof renderSimilar === "function") renderSimilar();
        else submit.disabled = originalSubmitDisabled;
      }
    }
  };
})();
