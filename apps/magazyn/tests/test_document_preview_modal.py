"""Documentation modal contracts. Synthetic SQLite only; original auth is unchanged."""
from html.parser import HTMLParser

from test_magazyn import scenario, auth, post
from test_electronics_documents_orders import doc_payload


class Ids(HTMLParser):
    def __init__(self):
        super().__init__()
        self.attrs = {}

    def handle_starttag(self, tag, attributes):
        data = dict(attributes)
        if "id" in data:
            assert data["id"] not in self.attrs, data["id"]
            self.attrs[data["id"]] = (tag, data)


def test_inline_modal_controls_and_safe_iframe(scenario):
    c, *_ = scenario
    html = c.get("/").text
    ids = Ids()
    ids.feed(html)
    expected = (
        "document-preview-dialog", "doc-preview-title", "doc-preview-filename",
        "doc-preview-status", "doc-preview-image", "doc-preview-pdf",
        "doc-preview-close", "doc-preview-dismiss", "doc-preview-download",
        "doc-preview-image-tools", "doc-zoom-in", "doc-zoom-out", "doc-zoom-fit",
        "doc-zoom-label",
    )
    for ident in expected:
        assert ident in ids.attrs
    assert ids.attrs["document-preview-dialog"][0] == "dialog"
    frame = ids.attrs["doc-preview-pdf"][1]
    assert "sandbox" in frame
    # The built-in PDF viewer needs scripts and access to its blob data.
    # All other iframe sandbox capabilities remain disabled.
    assert set(frame["sandbox"].split()) == {"allow-scripts", "allow-same-origin"}
    assert frame["referrerpolicy"] == "no-referrer"
    js = c.get("/static/electronics.js").text
    for snippet in (
        'class="small doc-preview"', "openElectronicDocumentPreview",
        "fetch(url,", "credentials:\"same-origin\"", 'cache:"no-store"',
        "URL.createObjectURL", "URL.revokeObjectURL",
        "documentPreviewController.abort()", "cleanupDocumentPreview",
        "response.headers.get(\"Content-Type\")",
        "openElectronicDocumentPreview(Number(view.dataset.documentId))",
    ):
        assert snippet in js
    assert "window.open(" not in js


def test_document_fetch_preserves_auth_attachment_and_csp(scenario):
    c, store, admin, worker = scenario
    token = auth(c)
    loc = store.add_location("VIEW-TEST")
    created = post(c, "/api/items/receive", {
        "kind": "part", "designation": "VIEWER-SYNTHETIC",
        "primary_number": "VIEWER-TEST-001", "category": "Układy scalone",
        "location_id": loc, "quantity": 1,
    }, token)
    assert created.status_code == 201, created.text
    item_id = created.json()["id"]
    doc = c.post(f"/api/items/{item_id}/documents", json=doc_payload(),
                 headers=token)
    assert doc.status_code == 201
    path = f"/api/items/{item_id}/documents/{doc.json()['id']}"
    retrieved = c.get(path)
    assert retrieved.status_code == 200
    assert retrieved.headers["content-type"].startswith("application/pdf")
    assert retrieved.headers["content-disposition"].startswith("attachment")
    assert retrieved.headers["cache-control"] == "no-store"
    assert retrieved.headers["x-frame-options"] == "DENY"
    assert retrieved.headers["x-content-type-options"] == "nosniff"
    policy = retrieved.headers["content-security-policy"]
    assert "img-src 'self' data: blob:" in policy
    assert "frame-src blob:" in policy
    assert "object-src 'none'" in policy
    assert "frame-ancestors 'none'" in policy
    c.post("/api/auth/logout", json={}, headers=token)
    assert c.get(path).status_code == 401
    assert c.get("/api/items/1/documents/999").status_code == 401


def test_modal_style_uses_existing_colors_and_mobile_safe_area(scenario):
    c, *_ = scenario
    css = c.get("/static/style.css").text
    for requirement in (
        "dialog.document-preview-dialog:not([open])",
        "dialog.document-preview-dialog[open]",
        "env(safe-area-inset-bottom",
        ".doc-preview-content #doc-preview-image",
        ".doc-preview-content #doc-preview-pdf",
        ".doc-preview-zoom-tools",
    ):
        assert requirement in css
    for theme in ("--orange: #B74B0D", "--graphite: #282D33",
                  "--page: #F5F5F4"):
        assert theme in css
