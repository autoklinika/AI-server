
uint16_t pressure_to_dtc(uint16_t pressure,uint8_t sensor_ok)

{
  uint16_t uVar1;
  uint8_t sensor_ok_local;
  uint16_t pressure_local;
  
  if (sensor_ok == '\0') {
    uVar1 = 0x1234;
  }
  else if (pressure < 0xfb) {
    uVar1 = 0;
  }
  else {
    uVar1 = 0x5678;
  }
  return uVar1;
}

