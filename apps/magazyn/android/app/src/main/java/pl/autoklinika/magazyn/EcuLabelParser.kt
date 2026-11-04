package pl.autoklinika.magazyn

/**
 * Conservative offline parsing of OCR results. Only clearly identified product
 * numbers are auto-filled. Ambiguous values remain selectable by the operator.
 * Never infer a vehicle brand from the ECU manufacturer.
 */
data class EcuScanResult(
    val manufacturer: String,
    val primaryNumber: String,
    val hardware: String,
    val software: String,
    val model: String,
    val candidates: List<String>,
    val barcodes: List<String>,
    val rawText: String
)

object EcuLabelParser {
    private val boschNumber = Regex("""(?<!\d)0[\s.-]*2\d{2}[\s.-]*\d{3}[\s.-]*\d{3}(?!\d)""")
    private val labeledNumber = Regex(
        """(?i)\b(?:P\s*/\s*N|PART\s*(?:NO\.?|NUMBER)|OEM|NR\s*KATALOGOWY)\s*[:#=\-]?\s*([A-Z0-9][A-Z0-9./ \-]{4,28})"""
    )
    private val ecuModel = Regex("""(?i)\b(?:EDC(?:7|15|16|17)[A-Z0-9-]{0,12}|MD1[A-Z0-9-]{2,15}|DCM\d[A-Z0-9-]{0,12})\b""")
    private val hardware = Regex("""(?i)\b(?:HW|H/W|HARDWARE)\s*[:#=\-]?\s*([A-Z0-9._/-]{2,30})""")
    private val software = Regex("""(?i)\b(?:SW|S/W|SOFTWARE)\s*[:#=\-]?\s*([A-Z0-9._/-]{2,30})""")

    private fun normalizedNumber(raw: String): String =
        raw.uppercase().filter { it in 'A'..'Z' || it in '0'..'9' }

    private fun validCandidate(candidate: String): Boolean =
        candidate.length in 7..25 && candidate.any(Char::isDigit)

    fun parse(ocrText: String, rawBarcodes: List<String>): EcuScanResult {
        val text = ocrText.take(6000)
        val barcodes = rawBarcodes.take(20)
            .map { it.trim().take(140) }
            .filter { it.isNotEmpty() }
            .distinct()
        val combined = text + "\n" + barcodes.joinToString("\n")
        val bosch = boschNumber.findAll(combined)
            .map { normalizedNumber(it.value) }.distinct().toList()
        val labeled = labeledNumber.findAll(text).mapNotNull { match ->
            val part = match.groupValues[1].split(Regex("""\s{2,}|[,;]"""))[0]
            val cleaned = normalizedNumber(part)
            cleaned.takeIf(::validCandidate)
        }.distinct().toList()

        val candidates = linkedSetOf<String>()
        candidates.addAll(bosch)
        candidates.addAll(labeled)
        for (raw in barcodes) {
            val cleaned = normalizedNumber(raw)
            if (validCandidate(cleaned)) candidates.add(cleaned)
        }

        // Multiple Bosch or multiple labeled numbers require operator choice.
        val primary = when {
            bosch.size == 1 -> bosch.single()
            bosch.isNotEmpty() -> ""
            labeled.size == 1 -> labeled.single()
            else -> ""
        }

        val manufacturer = when {
            Regex("""(?i)\bBOSCH\b""").containsMatchIn(text) || bosch.size == 1 -> "Bosch"
            Regex("""(?i)\b(?:CONTINENTAL|SIEMENS)\b""").containsMatchIn(text) -> "Continental"
            Regex("""(?i)\bDELPHI\b""").containsMatchIn(text) -> "Delphi"
            Regex("""(?i)\bDENSO\b""").containsMatchIn(text) -> "Denso"
            Regex("""(?i)\bMARELLI\b""").containsMatchIn(text) -> "Marelli"
            else -> ""
        }

        fun taggedValue(expression: Regex): String =
            expression.find(text)?.groupValues?.get(1)
                ?.takeUnless { it.equals("HW", true) || it.equals("SW", true) } ?: ""

        return EcuScanResult(
            manufacturer = manufacturer,
            primaryNumber = primary,
            hardware = taggedValue(hardware),
            software = taggedValue(software),
            model = ecuModel.find(text)?.value?.uppercase() ?: "",
            candidates = candidates.take(15),
            barcodes = barcodes,
            rawText = text
        )
    }
}
