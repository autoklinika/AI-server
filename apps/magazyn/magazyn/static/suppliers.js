"use strict";

/* Integrated Magazyn Ustawienia > Integracje > Hurtownie — DEV ONLY.
   Credentials travel directly to same-origin DEV API, never to other browser origins. */
let supplierLoadSequence = 0;

const supplierFields = {
  api_key: "Klucz API",
  client_token: "Token aplikacji",
  app_secret: "Sekret aplikacji",
  client_id: "Client ID",
  client_secret: "Client Secret",
  customer_id: "Customer ID (opcjonalnie)",
  contract_secret: "Sekret HMAC (opcjonalnie)"
};
const supplierStatusLabels = {
  ok: "Wyniki API",
  disabled: "Hurtownia wyłączona",
  offline_dev: "OFFLINE-DEV — brak połączenia sieciowego",
  credentials_required: "Uzupełnij dane autoryzacyjne",
  api_error: "Błąd API — sprawdź autoryzację lub parametry"
};

function resetSupplierUi() {
  supplierLoadSequence++;
  const container = byId("supplier-integration-list");
  if (!container) return;
  container.querySelectorAll('input[type="password"]').forEach(input => { input.value = ""; });
  const results = byId("supplier-results");
  if (results) results.replaceChildren();
}

function supplierQuery() {
  const query = byId("supplier-query").value.trim();
  if (query.length < 2 || query.length > 40) {
    throw new Error("Wprowadź oznaczenie elementu (2–40 znaków).");
  }
  return query;
}

async function loadSupplierSettings() {
  if (!session || session.role !== "admin") return;
  const seq = ++supplierLoadSequence;
  const host = byId("supplier-integration-list");
  const status = byId("supplier-integration-status");
  if (!host || !status) return;
  status.textContent = "Wczytywanie konfiguracji hurtowni...";
  try {
    const data = await api("/api/integrations/suppliers");
    if (seq !== supplierLoadSequence || !session || session.role !== "admin") return;
    status.textContent =
      "Środowisko: " + data.mode + " · Produkcja odłączona · " +
      (data.mode === "OFFLINE-DEV"
        ? "Zapytania do hurtowni zablokowane do czasu włączenia trybu testów LIVE-DEV."
        : "Zapytania zewnętrzne możliwe jedynie dla aktywnych i skonfigurowanych hurtowni.");
    host.replaceChildren();
    for (const supplier of data.providers) host.appendChild(buildSupplierForm(supplier));
  } catch (err) {
    if (seq === supplierLoadSequence) status.textContent =
      "Nie udało się pobrać konfiguracji DEV: " + err.message;
  }
}

function buildSupplierForm(supplier) {
  const article = document.createElement("article");
  article.className = "supplier-entry";
  article.classList.toggle("supplier-entry-ready", supplier.enabled && supplier.configured);
  const header = document.createElement("div");
  header.className = "supplier-entry-heading";
  const heading = document.createElement("h3");
  heading.textContent = supplier.name;
  heading.id = "supplier-heading-" + supplier.supplier;
  article.setAttribute("aria-labelledby", heading.id);
  const badge = document.createElement("span");
  badge.className = "tag";
  badge.textContent = supplier.auth === "api_key" ? "API KEY" : "OAuth 2.0";
  header.append(heading, badge);
  article.append(header);
  const state = document.createElement("span");
  state.className = "supplier-state " +
    (supplier.enabled && supplier.configured ? "supplier-state-ready" :
     supplier.enabled ? "supplier-state-pending" : "supplier-state-disabled");
  state.textContent = supplier.enabled && supplier.configured
    ? "Aktywna · dane zapisane"
    : supplier.enabled ? "Aktywna · brakuje klucza"
    : supplier.configured ? "Wyłączona · dane zapisane"
    : "Nie skonfigurowana";
  article.append(state);
  const hint = document.createElement("p");
  hint.className = "muted small-text";
  hint.textContent = supplier.description;
  article.append(hint);

  const form = document.createElement("form");
  form.className = "stack supplier-form";
  form.autocomplete = "off";
  const fields = document.createElement("div");
  fields.className = "supplier-fields";
  for (const field of supplier.fields) {
    const label = document.createElement("label");
    const status = supplier.saved_fields.includes(field) ? " · zapisano" : "";
    label.textContent = (supplierFields[field] || field) + status;
    const input = document.createElement("input");
    input.type = "password";
    input.name = field;
    input.maxLength = 512;
    input.autocomplete = "new-password";
    input.placeholder = supplier.saved_fields.includes(field) ? "Pozostaw puste — zachowaj klucz" : "Wprowadź dane DEV";
    label.append(input);
    fields.append(label);
  }
  form.append(fields);

  const controls = document.createElement("div");
  controls.className = "supplier-controls";
  const enabledLabel = document.createElement("label");
  enabledLabel.className = "supplier-toggle";
  const enabled = document.createElement("input");
  enabled.type = "checkbox";
  enabled.name = "enabled";
  enabled.checked = supplier.enabled;
  enabledLabel.append(enabled, document.createTextNode(" Aktywna"));
  const priorityLabel = document.createElement("label");
  priorityLabel.textContent = "Priorytet";
  const priority = document.createElement("input");
  priority.type = "number";
  priority.name = "priority";
  priority.min = "1";
  priority.max = "99";
  priority.value = supplier.priority;
  priorityLabel.append(priority);
  controls.append(enabledLabel, priorityLabel);
  form.append(controls);

  const actions = document.createElement("div");
  actions.className = "action-row supplier-actions";
  const save = document.createElement("button");
  save.type = "submit";
  save.className = "primary";
  save.textContent = "Zapisz";
  const test = document.createElement("button");
  test.type = "button";
  test.className = "secondary";
  test.textContent = "Test połączenia";
  const clear = document.createElement("button");
  clear.type = "button";
  clear.className = "secondary";
  clear.textContent = "Usuń klucze";
  actions.append(save, test, clear);
  form.append(actions);
  const result = document.createElement("p");
  result.className = "subtle-note";
  result.setAttribute("role", "status");
  result.textContent = supplier.configured
    ? "Wymagane dane zapisane. Klucze są zaszyfrowane w bazie testowej."
    : "Wymagane klucze API nie zostały jeszcze zapisane.";
  form.append(result);

  form.addEventListener("submit", async event => {
    event.preventDefault();
    if (!session || session.role !== "admin") return;
    const credentials = {};
    for (const field of supplier.fields) {
      const value = form.elements.namedItem(field).value;
      if (value) credentials[field] = value;
    }
    save.disabled = true;
    try {
      await api("/api/integrations/suppliers/" + encodeURIComponent(supplier.supplier), {
        method: "PUT",
        body: JSON.stringify({
          enabled: enabled.checked,
          priority: Number(priority.value),
          credentials
        })
      });
      for (const field of supplier.fields) form.elements.namedItem(field).value = "";
      toast("Zapisano ustawienia " + supplier.name + " w środowisku DEV.");
      await loadSupplierSettings();
    } catch (err) {
      result.textContent = "Błąd zapisu: " + err.message;
      toast(err.message, true);
    } finally {
      save.disabled = false;
    }
  });
  test.addEventListener("click", async () => {
    test.disabled = true;
    result.textContent = "Sprawdzanie źródła...";
    try {
      const response = await api(
        "/api/integrations/suppliers/" + encodeURIComponent(supplier.supplier) + "/test",
        { method: "POST", body: JSON.stringify({query: supplierQuery()}) }
      );
      result.textContent = (supplierStatusLabels[response.status] || response.status) +
        (response.http_status ? " (HTTP " + response.http_status + ")" : "") +
        (response.status === "ok" ? " · znalezionych: " + response.results.length : "");
      showSupplierResults({sources: [response]});
    } catch (err) {
      result.textContent = err.message;
      toast(err.message, true);
    } finally {
      test.disabled = false;
    }
  });
  clear.addEventListener("click", async () => {
    if (!confirm("Usunąć klucze DEV dla " + supplier.name + "?")) return;
    clear.disabled = true;
    try {
      await api("/api/integrations/suppliers/" + encodeURIComponent(supplier.supplier), {
        method: "PUT", body: JSON.stringify({clear: true, enabled: false})
      });
      toast("Usunięto klucze DEV: " + supplier.name);
      await loadSupplierSettings();
    } catch (err) {
      result.textContent = err.message;
    } finally {
      clear.disabled = false;
    }
  });
  article.append(form);
  return article;
}

function showSupplierResults(data) {
  const container = byId("supplier-results");
  if (!container) return;
  container.replaceChildren();
  for (const source of data.sources || []) {
    const group = document.createElement("div");
    group.className = "supplier-result-group";
    const title = document.createElement("strong");
    title.textContent = source.supplier.toUpperCase();
    const status = document.createElement("p");
    status.className = "muted small-text";
    status.textContent = supplierStatusLabels[source.status] || source.status;
    group.append(title, status);
    for (const row of source.results || []) {
      const detail = document.createElement("div");
      detail.className = "supplier-result-row";
      const title = document.createElement("strong");
      title.textContent = row.mpn || "(brak MPN)";
      const description = document.createElement("p");
      description.textContent = [row.manufacturer, row.description,
        row.exact_mpn ? "Dokładny MPN" : "Weryfikacja MPN wymagana"].filter(Boolean).join(" · ");
      detail.append(title, description);
      if (row.datasheet_url) {
        try {
          const url = new URL(row.datasheet_url);
          if (url.protocol === "https:") {
            const a = document.createElement("a");
            a.textContent = "Datasheet ↗";
            a.target = "_blank";
            a.rel = "noopener noreferrer";
            a.href = url.href;
            detail.append(a);
          }
        } catch {}
      }
      group.append(detail);
    }
    container.append(group);
  }
}

async function runSupplierSearch() {
  const button = byId("supplier-search-all");
  if (!session || session.role !== "admin") return;
  button.disabled = true;
  try {
    const response = await api("/api/integrations/suppliers/search", {
      method: "POST", body: JSON.stringify({query: supplierQuery()})
    });
    showSupplierResults(response);
  } catch (err) {
    toast(err.message, true);
  } finally {button.disabled = false;}
}

document.addEventListener("DOMContentLoaded", () => {
  const button = byId("supplier-search-all");
  if (button) button.addEventListener("click", runSupplierSearch);
});
