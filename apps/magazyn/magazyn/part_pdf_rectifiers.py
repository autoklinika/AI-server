"""Source-grounded rectifier datasheet extraction for the existing Magazyn form.

Designed for PDF text from ON Semiconductor and comparable data sheets.
Never interprets absolute maximum ratings as normal operating conditions.
Manufacturer, parameter and package proposals require literal page evidence.
"""
from __future__ import annotations

import re

def rectifier_document(pages: list[str]) -> bool:
    if not pages:
        return False
    cover=pages[0][:7000]
    return bool(re.search(
        r"(?i)\b(?:ultra\s*fast|fast[\s-]+recovery|power|switch[\s-]*mode)\s+rectifiers?\b",
        cover))

def only_packaging_variants(part_no: str, pages: list[str]) -> bool:
    """Exclude G/T4/T4G when evidence explicitly labels ordering-only variants.

    Does not globally treat suffixes as interchangeable. Other suffixes
    (B/A/N1/VM etc.) remain family variants requiring caution.
    """
    if not rectifier_document(pages):
        return False
    cover=pages[0]
    if "ORDERING INFORMATION" not in cover.upper():
        return False
    found=set(re.findall(
        r"(?<![A-Z0-9])"+re.escape(part_no.upper())+
        r"([A-Z0-9]{1,6})(?![A-Z0-9])",
        "\n".join(pages).upper()))
    if not found or not found.issubset({"G","T4","T4G"}):
        return False
    for suffix in found:
        listed=re.search(
            r"(?i)\b"+re.escape(part_no+suffix)+
            r"[ \t]+(?:DPAK|TO[-\s]?\d{2,4}|SOT[-\s]?\d{2,4})\b",
            cover)
        if not listed:
            return False
    if any("G" in suffix for suffix in found) and not re.search(
        r"(?i)\bPb[\s−-]*Free\b",cover):
        return False
    if any("T4" in suffix for suffix in found) and not re.search(
        r"(?i)(?:\bT4\b.{0,40}\bsuffix\b|\btape\s*(?:&|and)\s*reel\b|2500\s*(?:/|units))",
        cover):
        return False
    return True

def extract_rectifier(part_no: str, pages: list[str], add) -> None:
    """Emit manufacturer, diode category, package, VRRM, I_F(AV), Tj/Tstg, trr.

    add(field,value,verbatim_evidence) verifies evidence in the original
    page text before accepting it. No undocumented estimates are generated.
    """
    if not rectifier_document(pages):
        return
    cover=pages[0]
    tables="\n".join(pages[:2])
    if not re.search(
        r"(?i)(?<![A-Z0-9])"+re.escape(part_no)+r"(?![A-Z0-9])",cover):
        return

    type_match=re.search(r"(?i)\b(?:ultra\s*fast|power)\s+rectifiers?\b",cover)
    if type_match:
        add("category","Diody",type_match.group(0))
        kind="Dioda prostownicza"
        if re.search(r"(?i)\bultra\s*fast\b",cover):
            kind="Prostownik ultraszybki"
        if re.search(r"(?i)\bPer\s+Diode\b",tables) and re.search(
            r"(?i)\bPer\s+Device\b",tables):
            kind+=" (podwójny)"
        add("spec_interface",kind,type_match.group(0))

    # Header plus legal-page identity of ON Semiconductor, not a fabricated
    # manufacturer inferred from the part prefix or a distributor's metadata.
    maker=re.search(r"(?i)\bON[\s-]+Semiconductor\b","\n".join(pages))
    domain=re.search(r"(?i)\b(?:www\.)?onsemi\.com\b",cover)
    if maker and domain:
        add("manufacturer","ON Semiconductor",maker.group(0))
    elif domain:
        add("manufacturer","onsemi",domain.group(0))

    package=re.search(
        r"(?i)\b(DPAK|D2PAK|DPAK-?\d*|(?:TO|SOT|SOIC)[-\s]?\d{2,4})\s+"
        r"(?:Surface\s+Mount\s+)?Package\b",
        cover)
    if not package:
        package=re.search(r"(?i)\b(DPAK|D2PAK)\s+CASE\s+\d+[A-Z]?\b",cover)
    if package:
        add("package",package.group(1).upper().replace(" ",""),package.group(0))

    # Explicit table, not the headline's "6.0 AMPERES, 200 VOLTS".
    reverse=re.search(
        r"(?i)\bPeak\s+Repetitive\s+Reverse\s+Voltage[^\n]*"
        r"\bV\s*RRM\b[ \t]+(\d{1,4}(?:[.,]\d+)?)[ \t]+V\b",
        tables)
    if reverse:
        add("spec_voltage",reverse.group(1).replace(",",".")+
            " V (VRRM, maks. napięcie wsteczne)",reverse.group(0))

    current_section=re.search(
        r"(?is)\bAverage\s+Rectified\s+Forward\s+Current\b"
        r"([\s\S]{0,700}?)"
        r"(?=\bPeak\s+Repetitive\s+Forward\s+Current\b|"
        r"\bNon[\s−-]*Repetitive\s+Peak\s+Surge\b)",
        tables)
    if current_section:
        block=current_section.group(0)
        per_diode=re.search(r"(?i)\bPer\s+Diode[ \t]+(\d+(?:[.,]\d+)?)\b",block)
        per_device=re.search(r"(?i)\bPer\s+Device[ \t]+(\d+(?:[.,]\d+)?)\b",block)
        if per_diode and per_device and "IF(AV)" in block.upper():
            amp=per_device.group(1).replace(",",".")
            per=per_diode.group(1).replace(",",".")
            condition=re.search(r"(?i)\bT\s*C\s*=\s*(\d{1,3})\s*°?\s*C\b",block)
            at_tc=(" przy Tc="+condition.group(1)+"°C") if condition else ""
            add("spec_current",
                amp+" A (IF(AV) na element"+at_tc+"; "+per+" A na diodę)",
                per_device.group(0))

    temperature=re.search(
        r"(?i)\bOperating\s+Junction\s+and\s+Storage[^\n]*"
        r"\bT\s*J\s*,?\s*T\s*stg[ \t]+"
        r"([−\-]\s*\d{1,3}[ \t]+to[ \t]+\+?\d{1,3})[ \t]*°\s*C",
        tables)
    if temperature:
        value=temperature.group(1).replace("−","-")
        value=re.sub(r"\s+"," ",value)
        add("spec_temperature",
            value+" °C (Tj/Tstg; granice katalogowe)",temperature.group(0))

    recovery=re.search(
        r"(?i)\bUltrafast[ \t]+(\d{1,3})[ \t]+Nanosecond[ \t]+Recovery[ \t]+Time\b",
        cover)
    if recovery:
        add("parameters","Czas odzyskiwania trr: "+recovery.group(1)+
            " ns (warunki w datasheet)",recovery.group(0))
