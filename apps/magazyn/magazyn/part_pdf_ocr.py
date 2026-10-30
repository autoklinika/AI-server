"""Bounded CPU-only OCR for scanned electronics datasheets in Magazyn DEV.

Only called for PDF pages without a usable text layer. Does not use GPUs,
Ollama, the AI Resource Manager, any background service, or external network.
PDF pages and OCR images are piped through stdin/stdout, never stored to disk.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess

from .store import Problem

TOOL_ROOT=Path("/srv/ai-data/tools/tesseract-portable/root")
TESSERACT=TOOL_ROOT/"usr/bin/tesseract"
TESSDATA=TOOL_ROOT/"usr/share/tesseract-ocr/5/tessdata"
OCR_LIB=TOOL_ROOT/"usr/lib/x86_64-linux-gnu"
MAX_OCR_PAGES=6
MAX_IMAGE_BYTES=4_000_000
MAX_OUTPUT_BYTES=65_000


def available() -> bool:
    return (TESSERACT.is_file() and os.access(TESSERACT,os.X_OK)
            and (TESSDATA/"eng.traineddata").is_file()
            and (TESSDATA/"pol.traineddata").is_file())


def pdf_ocr_page(pdf_bytes: bytes, page_number: int) -> str:
    """Return text for one scanned page. Hard limits cap time and raster size."""
    if not available():
        raise Problem(503,"Lokalny OCR jest niedostępny. Możesz dołączyć PDF bez analizy.")
    if not isinstance(page_number,int) or not 1<=page_number<=12:
        raise ValueError("Invalid page number")
    try:
        # A pixel dimension bound limits PGM output to <= ~2.6 MB. The PGM
        # travels through pipes rather than temp files on the host.
        render=subprocess.run(
            ["pdftoppm","-f",str(page_number),"-l",str(page_number),
             "-scale-to","1600","-gray","-"],
            input=pdf_bytes,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
            timeout=11,check=False,
        )
    except (subprocess.TimeoutExpired,OSError):
        return ""
    image=render.stdout
    if (render.returncode!=0 or len(image)<100 or
            len(image)>MAX_IMAGE_BYTES or not image.startswith((b"P5\n",b"P2\n"))):
        return ""

    env=os.environ.copy()
    env["LD_LIBRARY_PATH"]=str(OCR_LIB)+":"+env.get("LD_LIBRARY_PATH","")
    env["TESSDATA_PREFIX"]=str(TESSDATA)
    env["OMP_THREAD_LIMIT"]="1"
    try:
        recognized=subprocess.run(
            [str(TESSERACT),"stdin","stdout","-l","eng+pol","--psm","6"],
            input=image,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
            env=env,timeout=15,check=False,
        )
    except (subprocess.TimeoutExpired,OSError):
        return ""
    if recognized.returncode or not recognized.stdout:
        return ""
    text=recognized.stdout[:MAX_OUTPUT_BYTES].decode("utf-8","replace")
    return text if len(re.findall(r"[A-Za-z0-9]",text))>=8 else ""
