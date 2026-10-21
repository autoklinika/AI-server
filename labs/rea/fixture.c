/* Synthetic ECU-like lookup; no customer firmware and never executed by REA. */
#include <stdint.h>
__attribute__((noinline)) uint16_t pressure_to_dtc(uint16_t pressure, uint8_t sensor_ok) {
    if (!sensor_ok) return 0x1234;
    if (pressure > 250) return 0x5678;
    return 0;
}
int main(int argc, char **argv) { (void)argv; return pressure_to_dtc((uint16_t)argc, 1); }
