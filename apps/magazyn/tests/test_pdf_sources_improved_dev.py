"""Regression: PDF URL and disk share exact-MPN evidence and safe attachment."""
from __future__ import annotations
import base64
from io import BytesIO
import subprocess
from unittest import TestCase
from unittest.mock import patch

from magazyn.part_datasheets import (
    _pdf_text, _pdf_bytes, _has_exact_mpn, DatasheetFinder, inspect_pdf,
    MAX_PDF_PAGES)
from magazyn.part_pdf_fetch import fetch_pdf, manufacturer_domain, SameManufacturerRedirect
from urllib.request import Request
from magazyn.part_datasheets import MANUFACTURER_PDF_HOSTS, _allowed_url
from magazyn.store import Problem

def make_text_pdf(lines):
    """Generate a minimal 1-font multi-page valid PDF without third-party libs."""
    pages=list(lines)
    objects=[b"",b"<< /Type /Catalog /Pages 2 0 R >>", b""]
    pages_obj=[]
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>") # obj 3? actually index 3
    for line in pages:
        page_ref=len(objects)
        content_ref=page_ref+1
        pages_obj.append(page_ref)
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {content_ref} 0 R >>".encode())
        text=str(line).replace("\\","\\\\").replace("(","\\(").replace(")","\\)")
        stream=("BT /F1 12 Tf 72 710 Td ("+text+") Tj ET").encode()
        objects.append(b"<< /Length "+str(len(stream)).encode()+b" >>\nstream\n"+stream+b"\nendstream")
    objects[2]=b"<< /Type /Pages /Kids ["+b" ".join(
        f"{n} 0 R".encode() for n in pages_obj)+b"] /Count "+str(len(pages)).encode()+b" >>"
    out=BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets=[0]
    for i in range(1,len(objects)):
        offsets.append(out.tell())
        out.write(f"{i} 0 obj\n".encode()+objects[i]+b"\nendobj\n")
    xref=out.tell()
    out.write(f"xref\n0 {len(objects)}\n".encode())
    out.write(b"0000000000 65535 f \n")
    for ofs in offsets[1:]:
        out.write(f"{ofs:010d} 00000 n \n".encode())
    out.write(b"trailer\n<< /Size "+str(len(objects)).encode()+b" /Root 1 0 R >>\n"
              b"startxref\n"+str(xref).encode()+b"\n%%EOF\n")
    return out.getvalue()


class TestPDFSourceImprovements(TestCase):
    def test_genuine_pdf_parses_beyond_six_pages(self):
        pdf=make_text_pdf(["Introduction only"]*7+
                          ["LM2309Y P-channel MOSFET datasheet"]+
                          ["Other descriptions"]*3)
        self.assertTrue(pdf.startswith(b"%PDF-"))
        pages=_pdf_text(pdf)
        self.assertEqual(len(pages),11)
        self.assertIn("LM2309Y", pages[7])
        self.assertTrue(_has_exact_mpn("LM2309Y",pages)[0])
        self.assertGreaterEqual(MAX_PDF_PAGES,11)

    def test_mpn_only_in_later_page_is_not_auto_filled(self):
        pdf=make_text_pdf(["Unrelated part / V DS = 99 V"]+
                          ["General catalog index"]*6+
                          ["LM2309Y also mentioned in compatibility list"])
        result=inspect_pdf(pdf,"LM2309Y")
        self.assertTrue(result["family_datasheet"])
        self.assertTrue(any("dalszych stronach" in w for w in result["warnings"]))
        fields={x["field"]:x for x in result["suggestions"]}
        self.assertEqual(fields["primary_number"]["confidence"],"verify_variant")
        self.assertNotIn("spec_voltage",fields)

    def test_local_pdf_analysis_does_not_echo_base64(self):
        pdf=make_text_pdf(["LM2309Y P-channel power MOSFET"]+
                          ["Other PDF page"]*2)
        result=DatasheetFinder().analyze_upload("LM2309Y",
                   base64.b64encode(pdf).decode())
        self.assertEqual(result["part_number"],"LM2309Y")
        self.assertEqual(result["source_kind"],"uploaded_pdf")
        self.assertTrue(result["document_already_selected"])
        self.assertNotIn("pdf_base64",result)
        self.assertTrue(result["manual_approval_required"])
        self.assertIn("primary_number",
                     [s["field"] for s in result["suggestions"]])

    def test_exact_mpn_not_equal_to_longer_suffix(self):
        pages=["LM2309 is present; LM2309Y not documented."]
        self.assertTrue(_has_exact_mpn("LM2309Y",pages)[0])
        self.assertTrue(_has_exact_mpn("LM2309",pages)[1])
        with self.assertRaises(Problem):
            inspect_pdf(make_text_pdf(["LM2309 known MOSFET"]),
                        "LM2309Y")

    def test_scanned_or_invalid_pdf_returns_guidance(self):
        with self.assertRaises(Problem):
            _pdf_bytes(base64.b64encode(b"hello world").decode())
        blank=make_text_pdf([" "])
        with self.assertRaises(Problem) as cm:
            _pdf_text(blank)
        self.assertEqual(cm.exception.status,422)
        self.assertTrue("tekst" in cm.exception.detail.lower())

    def test_link_uses_manufacturer_domain_not_distributor(self):
        finder=DatasheetFinder()
        for address in ("http://www.ti.com/lit/ds/symlink/lm358.pdf",
                        "https://127.0.0.1/lm358.pdf",
                        "https://evil.example/part.pdf",
                        "https://foo.ti.com.evil.example/file.pdf",
                        "https://www.mouser.com/file.pdf"):
            with self.assertRaises(Problem,msg=address):
                finder.analyze_url("LM358",address)

    def test_follow_only_same_manufacturer_redirect(self):
        url="https://www.ti.com/lit/ds/symlink/lm358.pdf"
        same="https://downloads.ti.com/file.pdf"
        wrong="https://evil.example/file.pdf"
        domain=manufacturer_domain(url,MANUFACTURER_PDF_HOSTS,_allowed_url)
        self.assertEqual(domain,"ti.com")
        self.assertEqual(manufacturer_domain(same,MANUFACTURER_PDF_HOSTS,
                                             _allowed_url),"ti.com")
        with self.assertRaises(Problem):
            manufacturer_domain(wrong,MANUFACTURER_PDF_HOSTS,_allowed_url)

    def test_redirects_only_within_same_manufacturer(self):
        handler=SameManufacturerRedirect("ti.com",MANUFACTURER_PDF_HOSTS,_allowed_url)
        original=Request("https://www.ti.com/lit/ds/symlink/lm358.pdf")
        allowed=handler.redirect_request(
            original,None,302,"Found",{},"https://downloads.ti.com/lit/lm358.pdf")
        self.assertEqual(allowed.full_url,"https://downloads.ti.com/lit/lm358.pdf")
        with self.assertRaises(Problem):
            handler.redirect_request(original,None,302,"Found",{},
                "https://www.nxp.com/docs/en/data-sheet/file.pdf")
        with self.assertRaises(Problem):
            handler.redirect_request(original,None,302,"Found",{},
                "https://192.0.2.1/file.pdf")
        self.assertEqual(handler.hops,3)

    def test_download_limit_is_enforced_before_reading(self):
        class HugeResponse:
            headers={"Content-Length":str(8*1024*1024+1)}
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,n):raise AssertionError("must not read oversized document")
        class Client:
            def open(self,*args,**kwargs):return HugeResponse()
        with patch("magazyn.part_pdf_fetch.build_opener",return_value=Client()):
            with self.assertRaises(Problem) as error:
                fetch_pdf("https://www.ti.com/lit/ds/symlink/lm358.pdf",
                    8*1024*1024,MANUFACTURER_PDF_HOSTS,_allowed_url)
        self.assertEqual(error.exception.status,413)

    def test_download_is_validated_as_pdf(self):
        pdf=make_text_pdf(["LM358"])
        class FakeResponse:
            headers={"Content-Length":str(len(pdf)),
                     "Content-Type":"application/pdf"}
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,n):return pdf[:n]
        class FakeClient:
            def open(self, request, timeout):return FakeResponse()
        with patch("magazyn.part_pdf_fetch.build_opener",return_value=FakeClient()):
            result=fetch_pdf("https://www.ti.com/lit/ds/symlink/lm358.pdf",
                         8*1024*1024,MANUFACTURER_PDF_HOSTS,_allowed_url)
        self.assertEqual(result,pdf)
        class FakeHtml(FakeResponse):
            def read(self,n):return b"<html>no PDF</html>"
        class HtmlClient:
            def open(self,request,timeout):return FakeHtml()
        with patch("magazyn.part_pdf_fetch.build_opener",return_value=HtmlClient()):
            with self.assertRaises(Problem):
                fetch_pdf("https://www.ti.com/lit/ds/symlink/lm358.pdf",
                          8*1024*1024,MANUFACTURER_PDF_HOSTS,_allowed_url)

if __name__=="__main__":
    import unittest
    unittest.main(verbosity=2)
