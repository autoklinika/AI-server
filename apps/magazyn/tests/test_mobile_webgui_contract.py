"""Mobile WebGUI contract tests: no changes to data, roles, or desktop workflow."""
from html.parser import HTMLParser
from pathlib import Path

from test_magazyn import scenario, auth


class Elements(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []
        self.nav = []
        self.inputs = {}

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if "id" in attrs:
            self.ids.append(attrs["id"])
            if tag == "input":
                self.inputs[attrs["id"]] = attrs
        if tag == "button" and "data-tab" in attrs:
            self.nav.append(attrs["data-tab"])


def test_mobile_navigation_reuses_existing_tabs_and_has_safe_viewport(scenario):
    client, *_ = scenario
    page = client.get("/").text
    document = Elements()
    document.feed(page)
    assert "viewport-fit=cover" in page
    assert len(document.ids) == len(set(document.ids))
    assert document.nav == ["products", "low", "inventory", "history", "admin"]
    assert 'class="nav-item admin-only"' in page
    assert "nav-label-compact" in page
    assert document.inputs["search"]["enterkeyhint"] == "search"
    assert document.inputs["search"]["autocapitalize"] == "off"


def test_mobile_css_has_safe_bottom_navigation_and_touch_targets(scenario):
    client, *_ = scenario
    css = client.get("/static/style.css").text
    assert "--orange: #B74B0D;" in css
    assert "--graphite: #282D33;" in css
    assert "--page: #F5F5F4;" in css
    assert "@media (max-width: 650px)" in css
    mobile = css.split("/* Magazyn V1 mobile ergonomics", 1)[1]
    for requirement in (
        "env(safe-area-inset-bottom", "position: fixed", ".sidebar nav.admin-only",
        ".product-actions button:not(:first-child)", "min-height: 44px !important",
        ".quantity-stepper .stepper-btn", "font-size: 16px",
        "#inventory-results td::before", ".history-table td::before",
        ".auth-wrapper", ".dialog-head", "#page-products > .catalog-panel { order: 1; }",
    ):
        assert requirement in mobile


def test_mobile_history_and_inventory_keep_labels_and_crud_permissions(scenario):
    client, store, admin_id, worker_id = scenario
    html = client.get("/").text
    js = client.get("/static/app.js").text
    assert '<button class="primary add-main"' in html
    assert 'id="operation-reason"' in html
    assert '<option value="repair">' in html
    assert "data-label=\"Oczekiwane\"" in js
    assert "data-label=\"Policzone\"" in js
    assert "data-label=\"Różnica\"" in js
    assert "data-label=\"Użytkownik\"" in js
    assert "data-label=\"Produkt\"" in js
    assert "session.role===\"admin\"" in js
    assert 'byId("login-form").reset()' in js
    # Existing backend RBAC remains authoritative, not the mobile CSS.
    worker = auth(client, "worker1", "second-test-password-456")
    assert client.get("/api/users").status_code == 403
    assert client.post("/api/backup/manual", json={}, headers=worker).status_code == 403
    assert client.post("/api/inventory", json={
        "location_id": 1, "rows": []}, headers=worker).status_code in (403, 422)


def test_mobile_still_uses_only_original_stock_endpoints(scenario):
    client, *_ = scenario
    js = client.get("/static/app.js").text
    assert '"/api/items/"' in js
    assert '"/api/stock"' in js
    assert '"quick-receive"' in js and '"quick-issue"' in js
    assert 'reason.required=action==="issue"' in js
    assert 'byId("operation-submit").disabled=!valid' in js
