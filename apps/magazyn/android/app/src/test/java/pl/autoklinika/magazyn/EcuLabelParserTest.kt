package pl.autoklinika.magazyn

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class EcuLabelParserTest {
    @Test fun boschNumberWithSpaces() {
        val scan = EcuLabelParser.parse("BOSCH\n0 281 016 738\nEDC17C46\nHW: 03\nSW: 123456", emptyList())
        assertEquals("0281016738", scan.primaryNumber)
        assertEquals("Bosch", scan.manufacturer)
        assertEquals("EDC17C46", scan.model)
        assertEquals("03", scan.hardware)
        assertEquals("123456", scan.software)
    }

    @Test fun differentBoschNumbersRequireConfirmation() {
        val scan = EcuLabelParser.parse("0 281 016 738\n0 281 016 739", emptyList())
        assertEquals("", scan.primaryNumber)
        assertEquals(2, scan.candidates.size)
    }

    @Test fun usesExplicitPartNumber() {
        val scan = EcuLabelParser.parse("Continental\nP/N: A2C12345678", emptyList())
        assertEquals("A2C12345678", scan.primaryNumber)
        assertEquals("Continental", scan.manufacturer)
    }

    @Test fun barcodeWithoutLabelIsNotAutomaticallyMainNumber() {
        val scan = EcuLabelParser.parse("S/N 123456789", listOf("123456789"))
        assertEquals("", scan.primaryNumber)
        assertTrue(scan.candidates.contains("123456789"))
    }

    @Test fun barcodeWithBoschNumberIsRecognized() {
        val scan = EcuLabelParser.parse("", listOf("0281016738"))
        assertEquals("0281016738", scan.primaryNumber)
    }

    @Test fun noInventionWhenUncertain() {
        val scan = EcuLabelParser.parse("damaged label\nSW:", emptyList())
        assertEquals("", scan.primaryNumber)
        assertEquals("", scan.manufacturer)
        assertEquals("", scan.software)
    }
}
