"""Realistic synthetic ECU label transcriptions. No user photos, GPU or SQLite."""
from magazyn.ecu_label_fields import classify


def test_bosch_ecu_with_oem_hw_sw_and_serial_on_one_line():
    label = (
        "BOSCH\n0 281 016 738\nEDC17C46\n"
        "OEM: 03L 906 022 GC\n"
        "HW: H1   SW: S3\n"
        "S/N: 987654321\n"
    )
    r = classify(label, "BOSCH 0 281 016 738\nHW: H1 SW: S3", ["987654321"])
    assert r["primaryNumber"] == "0281016738"
    assert r["oemNumbers"] == ["03L906022GC"]
    assert r["manufacturer"] == "Bosch"
    assert r["designation"] == "Bosch EDC17C46"
    assert r["model"] == "EDC17C46"
    assert r["hardware"] == "H1"
    assert r["software"] == "S3"
    assert r["serialNumber"] == "987654321"
    assert "987654321" not in r["candidates"]
    assert "987654321" not in r["oemNumbers"]
    assert r["vehicleBrand"] == ""  # OEM cannot prove vehicle application.


def test_continental_part_number_and_oem_separate():
    label = (
        "CONTINENTAL\n"
        "VEHICLE: DAF\n"
        "SID807\n"
        "P/N: A2C12345678 HW: H23 SW: S4\n"
        "OEM: 1862828\n"
        "S/N: 123456789\n"
    )
    r = classify(label, "", [])
    assert r["primaryNumber"] == "A2C12345678"
    assert r["vehicleBrand"] == "DAF"
    assert r["manufacturer"] == "Continental"
    assert r["model"] == "SID807"
    assert r["designation"] == "Continental SID807"
    assert r["oemNumbers"] == ["1862828"]
    assert r["hardware"] == "H23"
    assert r["software"] == "S4"
    assert r["serialNumber"] == "123456789"


def test_oem_only_can_be_primary_but_never_serial():
    r = classify("OEM: 03L 906 022 GC\nS/N: 12345678\nSW: 10025", "", ["12345678"])
    assert r["primaryNumber"] == "03L906022GC"
    assert r["oemNumbers"] == []
    assert r["software"] == "10025"
    assert "12345678" not in r["candidates"]


def test_only_serial_and_unlabeled_barcode_never_fills_catalog():
    r = classify("S/N: 987654321\nHW: 045\nSW: 021", "", ["987654321"])
    assert r["primaryNumber"] == ""
    assert r["candidates"] == []
    assert r["hardware"] == "045"
    assert r["software"] == "021"


def test_disagreement_does_not_silently_change_a_digit():
    r = classify("BOSCH\n0 281 016 738", "BOSCH\n0 281 016 739", [])
    assert r["primaryNumber"] == ""
    assert r["candidates"] == ["0281016738", "0281016739"]
    assert r["warnings"]


def test_two_bosch_numbers_require_operator_choice():
    r = classify("BOSCH\n0 281 016 738\n0 281 016 739", "", [])
    assert r["primaryNumber"] == ""
    assert len(r["candidates"]) == 2


def test_unlabeled_generic_digits_do_not_create_oem():
    r = classify("Bosch\n0 281 016 738\n123456789\n2026/02/17", "", [])
    assert r["primaryNumber"] == "0281016738"
    assert r["oemNumbers"] == []


def test_brand_not_guessed_from_bosch_oem_prefix():
    r = classify("BOSCH\n0 281 016 738\nOEM: 03L 906 022 GC", "", [])
    assert r["vehicleBrand"] == ""
    assert r["designation"] == ""  # No explicit ECU model.


def test_hw_sw_conflict_stays_empty_not_guessed():
    r = classify("BOSCH\n0 281 016 738\nHW: H1\nSW: S3",
                 "BOSCH\n0 281 016 738\nHW: H2\nSW: S4", [])
    assert r["hardware"] == ""
    assert r["software"] == ""
    assert len(r["warnings"]) >= 2


def test_serial_only_keeps_phone_ocr_serial():
    r = classify("Continental\nS/N: 987654321\nHW: 01",
                 "Serial 987654321", ["987654321"])
    assert r["serialNumber"] == "987654321"
    assert r["primaryNumber"] == ""


def test_suspected_oem_in_barcode_not_injected_as_alias():
    r = classify("BOSCH\n0 281 016 738", "", ["0281016738", "AB1234567"])
    assert r["primaryNumber"] == "0281016738"
    assert r["oemNumbers"] == []
    assert "AB1234567" in r["candidates"]
