"""Offline evidence-grounded, structured ECU field mapping tests, no GPU."""
import json

from magazyn.ecu_smart_extract import enrich


def labels(raw, structured, phone="", barcodes=None):
    return enrich(raw, phone, barcodes or [], json.dumps(structured))


def test_structured_raises_field_coverage_on_engine_ecu_label():
    transcript = (
        "BOSCH\nENGINE CONTROL UNIT\n0 281 016 738\n"
        "EDC17C46\n03L 906 022 GC\n"
        "HW: H1 SW: S3\nS/N: 987654321\n"
        "Date: 2024-02-17\nVW\n"
    )
    result = labels(transcript, {
        "manufacturer": "Bosch",
        "vehicle_brand": "VW",
        "ecu_model": "EDC17C46",
        "category": "ECU silnika",
        "primary_number": "0281016738",
        "oem_numbers": ["03L906022GC"],
        "supplier_numbers": [],
        "hardware": "H1", "software": "S3",
        "serial_number": "987654321",
        "production_date": "2024-02-17",
        "other_numbers": [], "warnings": [],
    })
    assert result["primaryNumber"] == "0281016738"
    assert result["vehicleBrand"] == "Volkswagen"
    assert result["manufacturer"] == "Bosch"
    assert result["designation"] == "Bosch EDC17C46"
    assert result["hardware"] == "H1" and result["software"] == "S3"
    assert result["category"] == "ECU silnika"
    assert result["productionDate"] == "2024-02-17"
    assert result["serialNumber"] == "987654321"
    # Unlabelled OEM must be reviewable, not silently added.
    assert result["oemNumbers"] == []
    assert result["extraNumbers"] == [
        {"value": "03L906022GC", "role": "oem", "confidence": "suggestion"}
    ]


def test_continental_uses_ai_to_find_nonstandard_supplier_number():
    transcript = (
        "CONTINENTAL\nSID807EVO\nDAF\n"
        "A2C12345678\n5WK96745\nOEM: 1862828\n"
        "HW: 04 SW: 22.1\n"
    )
    result = labels(transcript, {
        "manufacturer": "Continental", "vehicle_brand": "DAF",
        "ecu_model": "SID807EVO",
        "primary_number": "A2C12345678",
        "oem_numbers": ["1862828"],
        "supplier_numbers": ["5WK96745"],
        "hardware": "04", "software": "22.1",
        "serial_number": "", "production_date": "",
        "category": "", "other_numbers": [], "warnings": []
    })
    assert result["primaryNumber"] == "A2C12345678"
    assert result["fieldConfidence"]["primary_number"] == "suggestion"
    assert result["model"] == "SID807EVO"
    assert result["designation"] == "Continental SID807EVO"
    assert result["vehicleBrand"] == "DAF"
    assert result["oemNumbers"] == ["1862828"]
    assert result["extraNumbers"] == [
        {"value": "5WK96745", "role": "supplier", "confidence": "suggestion"}
    ]
    assert result["hardware"] == "04"
    assert result["software"] == "22.1"


def test_hallucinated_identifiers_not_proposed():
    result = labels("BOSCH\n0 281 016 738\nHW: 05\nS/N: 123456789", {
        "primary_number": "0281016738", "oem_numbers": ["999999999"],
        "supplier_numbers": ["FAKE123456"],
        "other_numbers": ["NONEXISTENT111"],
        "hardware": "99", "software": "01",
        "serial_number": "123456789",
        "production_date": "2025-01-01",
        "manufacturer": "BOSH", "vehicle_brand": "MAN", "ecu_model": "EDC17C46",
        "category": "ECU silnika"
    })
    assert result["primaryNumber"] == "0281016738"
    assert result["manufacturer"] == "Bosch"
    assert result["hardware"] == "05"
    assert result["serialNumber"] == "123456789"
    assert result["vehicleBrand"] == ""
    assert result["oemNumbers"] == []
    assert result["extraNumbers"] == []
    assert result["productionDate"] == ""
    assert result.get("category", "") == ""


def test_no_duplicate_or_protected_values_as_aliases():
    result = labels(
        "BOSCH\nP/N: 0281016738\nOEM: 03L906022GC\nHW: H1\nSW: S3\nS/N: 987654321",
        {"primary_number": "0281016738",
         "oem_numbers": ["03L906022GC", "987654321", "0281016738"],
         "supplier_numbers": ["987654321", "03L906022GC"],
         "other_numbers": ["987654321", "0281016738", "H1"]},
    )
    assert result["primaryNumber"] == "0281016738"
    assert result["oemNumbers"] == ["03L906022GC"]
    assert result["extraNumbers"] == []


def test_model_json_malformed_uses_rule_parser():
    result = enrich("BOSCH\n0 281 016 738\nEDC17C46\nHW: H1\nSW: S3",
                    "", [], "This is not a JSON reply.")
    assert result["primaryNumber"] == "0281016738"
    assert result["model"] == "EDC17C46"
    assert result["extractionMode"] == "rules_fallback"
    assert result["warnings"]


def test_unlabelled_barcode_alone_is_not_confirmed_catalog():
    result = labels("S/N: 987654321\nDate: 2024-02-17", {
        "primary_number": "987654321",
        "oem_numbers": ["987654321"],
        "other_numbers": ["987654321"],
        "production_date": "2024-02-17",
        "serial_number": "987654321"
    }, barcodes=["987654321"])
    assert result["serialNumber"] == "987654321"
    assert result["primaryNumber"] == ""
    assert result["oemNumbers"] == []
    assert result["extraNumbers"] == []


def test_classification_does_not_require_an_online_lookup():
    result = labels("SIEMENS VDO\n5WK96745\nSID807\nEBS", {
        "manufacturer": "Continental", "ecu_model": "SID807",
        "primary_number": "5WK96745", "category": "EBS"
    })
    assert result["primaryNumber"] == "5WK96745"
    assert result["category"] == "EBS"
    assert result["manufacturer"] == "Continental"
