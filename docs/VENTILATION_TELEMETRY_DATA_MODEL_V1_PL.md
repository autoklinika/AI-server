# Ventilation Telemetry Data Model v1

**Status:** zatwierdzony model danych do implementacji  
**Projekt:** AI Server / AI Bridge + Workshop Ventilation Controller  
**Wersja:** `1`  
**Data:** 08.08.2026

## 1. Cel

Dokument definiuje zawartość pola `metrics` używanego przez `Ventilation Telemetry API v1`.

Źródłem prawdy jest rzeczywisty, autorytatywny `CoreState` procesu `ventilation-core` na CM5.

AI Bridge nie może tworzyć alternatywnego, konkurencyjnego modelu stanu wentylacji.

Powiązany kontrakt transportowy:

`docs/VENTILATION_TELEMETRY_API_V1_PL.md`

## 2. Granica odpowiedzialności

AI Bridge nie odczytuje bezpośrednio:

- SENSOR BUS,
- Modbus RTU,
- UART,
- DFR0845,
- I²C,
- DFR0971.

Wyłącznym źródłem danych dla synchronizacji jest stan publikowany przez `ventilation-core`.

Dzięki temu AI Bridge nie zna sprzętowych szczegółów komunikacyjnych CM5 i nie tworzy równoległej ścieżki dostępu do urządzeń.

## 3. Snapshot telemetryczny

Pojedynczy rekord synchronizacyjny reprezentuje snapshot aktualnego `CoreState`.

Pole:

```text
captured_at
```

oznacza czas wykonania snapshotu stanu przez CM5.

Nie używamy dla całego snapshotu nazwy `measured_at`, ponieważ dwa węzły SEN55 są odpytywane niezależnie i posiadają własną informację o wieku, sekwencji i czasie ostatniego poprawnego odczytu.

Przykład otoczki rekordu:

```json
{
  "sample_id": "01K1ABCDE987654321XYZ98765",
  "sequence": 184928,
  "captured_at": "2026-08-08T13:29:55.250+02:00",
  "metrics": {}
}
```

`sample_id`, `sequence` i `captured_at` są elementami mechanizmu synchronizacji AI Bridge. Nie są pomiarami SEN55.

## 4. Struktura `metrics`

`metrics` odwzorowuje aktualny `CoreState` CM5.

```json
{
  "metrics": {
    "mode": "MANUAL",
    "setpoints": {
      "supply_voltage": 6.0,
      "extract_voltage": 6.0
    },
    "hardware_ready": true,
    "output_state_known": true,
    "consecutive_hardware_failures": 0,
    "active_alarms": [],
    "sensor_bus": {}
  }
}
```

## 5. Tryb pracy

Pole:

```text
mode
```

przyjmuje według aktualnej implementacji:

```text
STOP
MANUAL
FAULT
```

Na obecnym etapie kontrakt nie definiuje trybów `AUTO` ani `BOOST`, ponieważ nie są jeszcze zaimplementowane w `ventilation-core`.

Po ich rzeczywistej implementacji i walidacji kontrakt może zostać rozszerzony.

## 6. Wentylatory — aktualne setpointy

Aktualna telemetria wentylatorów pochodzi z:

```text
setpoints
```

Struktura:

```json
{
  "setpoints": {
    "supply_voltage": 6.0,
    "extract_voltage": 6.0
  }
}
```

Znaczenie:

- `supply_voltage` — zadane napięcie sterujące 0–10 V dla wentylatora nawiewnego,
- `extract_voltage` — zadane napięcie sterujące 0–10 V dla wentylatora wyciągowego.

Jednostka: `V`.

Są to setpointy sterujące znane przez CM5. Nie są to:

- zmierzone napięcia,
- RPM,
- częstotliwość tacho,
- rzeczywisty przepływ powietrza.

Ventilation Telemetry API v1 nie zawiera obecnie pól RPM/tacho. Zostaną dodane dopiero po implementacji i sprzętowej walidacji pomiaru tacho na CM5.

## 7. Diagnostyka toru sterowania wentylatorami

Aktualny `CoreState` udostępnia:

```json
{
  "hardware_ready": true,
  "output_state_known": true,
  "consecutive_hardware_failures": 0
}
```

### `hardware_ready`

Informuje, czy tor sterowania DAC jest gotowy do bezpiecznego przyjmowania poleceń.

### `output_state_known`

Informuje, czy CM5 uważa stan wyjść DAC za znany.

### `consecutive_hardware_failures`

Liczba kolejnych wykrytych błędów sprzętowych toru DAC.

## 8. Alarmy

Aktualne alarmy są przesyłane jako lista:

```json
{
  "active_alarms": [
    {
      "code": "DAC_COMMUNICATION_LOST",
      "severity": "critical",
      "message": "Brak komunikacji z DAC DFR0971",
      "active_since": "2026-08-08T11:23:10+00:00",
      "last_error": "example error",
      "occurrences": 3
    }
  ]
}
```

Jeżeli nie ma aktywnych alarmów:

```json
{
  "active_alarms": []
}
```

AI Bridge może analizować alarmy, ale nie może ich kasować, potwierdzać ani zmieniać ich wpływu na sterowanie.

## 9. SENSOR BUS

Aktualny `SensorBusState` może zostać przekazany bez tworzenia alternatywnego modelu danych.

Struktura:

```json
{
  "sensor_bus": {
    "port": "/dev/ttyAMA0",
    "baudrate": 19200,
    "addresses": [1, 2],
    "ready": true,
    "worker_alive": true,
    "worker_restarts": 0,
    "expected_map_version": 1,
    "inter_node_delay_seconds": 0.01,
    "poll_interval_seconds": 1.0,
    "last_cycle_at": "2026-08-08T11:29:55+00:00",
    "last_error": null,
    "nodes": []
  }
}
```

Parametry takie jak port, baudrate i okres odpytywania są informacją diagnostyczną CM5. AI Bridge nie wykorzystuje ich do komunikacji z urządzeniami.

## 10. Węzły SEN55

Aktualnie SENSOR BUS zawiera dwa węzły Modbus:

```text
slave 1
slave 2
```

Nie przypisujemy w kontrakcie v1 wymyślonych nazw pomieszczeń ani stref.

Identyfikatorem węzła pozostaje:

```text
slave_address
```

dopóki mapowanie fizycznego węzła na semantyczną lokalizację nie zostanie jawnie skonfigurowane.

Przykład:

```json
{
  "slave_address": 1,
  "online": true,
  "usable": true,
  "measurement_valid": true,
  "measurement_stale": false,
  "sensor_present": true,
  "availability_mask": 255,
  "status_mask": 3,
  "reading": {},
  "age_seconds": 0,
  "sensor_errors": 0,
  "modbus_service_errors": 0,
  "uptime_seconds": 123456,
  "firmware_version": "0.3",
  "map_version": 1,
  "sequence": 12345,
  "last_success_at": "2026-08-08T11:29:55+00:00",
  "last_error": null,
  "polls": 45678,
  "successful_polls": 45678,
  "communication_errors": 0,
  "consecutive_failures": 0,
  "invalid_measurements": 0,
  "stale_measurements": 0,
  "map_version_errors": 0
}
```

## 11. Znaczenie diagnostyki węzła

### Stan dostępności

- `online` — komunikacja Modbus z węzłem działa,
- `usable` — dane węzła spełniają kryteria użyteczności CM5,
- `measurement_valid` — pomiar został oznaczony jako ważny,
- `measurement_stale` — pomiar jest przeterminowany,
- `sensor_present` — SEN55 jest obecny według statusu węzła.

### Maski

- `availability_mask` — dostępność poszczególnych pól pomiarowych,
- `status_mask` — status pomiaru i stanu węzła.

### Diagnostyka czasowa i firmware

- `age_seconds` — wiek pomiaru raportowany przez węzeł,
- `uptime_seconds` — uptime węzła,
- `firmware_version` — wersja firmware KAmod,
- `map_version` — wersja mapy Modbus,
- `sequence` — sekwencja pomiarowa raportowana przez węzeł,
- `last_success_at` — czas ostatniego udanego odczytu przez CM5.

### Diagnostyka błędów

- `sensor_errors`,
- `modbus_service_errors`,
- `last_error`,
- `polls`,
- `successful_polls`,
- `communication_errors`,
- `consecutive_failures`,
- `invalid_measurements`,
- `stale_measurements`,
- `map_version_errors`.

Te pola są telemetrią diagnostyczną. Qwen może je interpretować, ale nie mogą bezpośrednio sterować wentylacją.

## 12. Pomiary SEN55

`reading` ma dokładnie strukturę aktualnie publikowaną przez CM5:

```json
{
  "reading": {
    "pm1_0_ug_m3": 4.2,
    "pm2_5_ug_m3": 6.1,
    "pm4_0_ug_m3": 7.3,
    "pm10_0_ug_m3": 8.0,
    "humidity_percent": 48.5,
    "temperature_celsius": 22.7,
    "voc_index": 97.0,
    "nox_index": 1.0
  }
}
```

Jednostki i znaczenie:

| Pole | Jednostka / znaczenie |
|---|---|
| `pm1_0_ug_m3` | µg/m³ |
| `pm2_5_ug_m3` | µg/m³ |
| `pm4_0_ug_m3` | µg/m³ |
| `pm10_0_ug_m3` | µg/m³ |
| `humidity_percent` | % RH |
| `temperature_celsius` | °C |
| `voc_index` | Sensirion VOC Index |
| `nox_index` | Sensirion NOx Index |

Nie dodajemy obecnie:

- CO₂,
- ciśnienia,
- airflow,
- RPM,
- innych wartości, których aktualny system nie dostarcza.

## 13. Niedostępne pomiary

Jeżeli SEN55 oznaczy określone pole jako niedostępne, CM5 reprezentuje je jako `null`.

Przykład:

```json
{
  "temperature_celsius": null
}
```

AI Bridge zachowuje tę wartość jako brak danych i nie zastępuje jej wartością `0`, `-1` ani inną sztuczną liczbą.

## 14. Przykładowy kompletny `metrics`

```json
{
  "metrics": {
    "mode": "MANUAL",
    "setpoints": {
      "supply_voltage": 6.0,
      "extract_voltage": 5.5
    },
    "hardware_ready": true,
    "output_state_known": true,
    "consecutive_hardware_failures": 0,
    "active_alarms": [],
    "sensor_bus": {
      "port": "/dev/ttyAMA0",
      "baudrate": 19200,
      "addresses": [1, 2],
      "ready": true,
      "worker_alive": true,
      "worker_restarts": 0,
      "expected_map_version": 1,
      "inter_node_delay_seconds": 0.01,
      "poll_interval_seconds": 1.0,
      "last_cycle_at": "2026-08-08T11:29:55+00:00",
      "last_error": null,
      "nodes": [
        {
          "slave_address": 1,
          "online": true,
          "usable": true,
          "measurement_valid": true,
          "measurement_stale": false,
          "sensor_present": true,
          "availability_mask": 255,
          "status_mask": 3,
          "reading": {
            "pm1_0_ug_m3": 4.2,
            "pm2_5_ug_m3": 6.1,
            "pm4_0_ug_m3": 7.3,
            "pm10_0_ug_m3": 8.0,
            "humidity_percent": 48.5,
            "temperature_celsius": 22.7,
            "voc_index": 97.0,
            "nox_index": 1.0
          },
          "age_seconds": 0,
          "sensor_errors": 0,
          "modbus_service_errors": 0,
          "uptime_seconds": 123456,
          "firmware_version": "0.3",
          "map_version": 1,
          "sequence": 12345,
          "last_success_at": "2026-08-08T11:29:55+00:00",
          "last_error": null,
          "polls": 45678,
          "successful_polls": 45678,
          "communication_errors": 0,
          "consecutive_failures": 0,
          "invalid_measurements": 0,
          "stale_measurements": 0,
          "map_version_errors": 0
        },
        {
          "slave_address": 2,
          "online": true,
          "usable": true,
          "measurement_valid": true,
          "measurement_stale": false,
          "sensor_present": true,
          "availability_mask": 255,
          "status_mask": 3,
          "reading": {
            "pm1_0_ug_m3": 5.0,
            "pm2_5_ug_m3": 7.2,
            "pm4_0_ug_m3": 8.1,
            "pm10_0_ug_m3": 9.0,
            "humidity_percent": 47.8,
            "temperature_celsius": 22.4,
            "voc_index": 91.0,
            "nox_index": 1.0
          },
          "age_seconds": 0,
          "sensor_errors": 0,
          "modbus_service_errors": 0,
          "uptime_seconds": 123450,
          "firmware_version": "0.3",
          "map_version": 1,
          "sequence": 12342,
          "last_success_at": "2026-08-08T11:29:55+00:00",
          "last_error": null,
          "polls": 45678,
          "successful_polls": 45678,
          "communication_errors": 0,
          "consecutive_failures": 0,
          "invalid_measurements": 0,
          "stale_measurements": 0,
          "map_version_errors": 0
        }
      ]
    }
  }
}
```

## 15. Świadomie nieobecne dane w v1

Model v1 nie definiuje obecnie jako rzeczywistych danych:

- RPM/tacho wentylatora nawiewnego,
- RPM/tacho wentylatora wyciągowego,
- danych AERO BUS/rekuperatora,
- CO₂,
- przepływu powietrza,
- trybów AUTO/BOOST,
- semantycznych nazw lokalizacji dwóch SEN55.

Pola te mogą zostać dodane dopiero po ich rzeczywistej implementacji i walidacji po stronie `ventilation-core`.

## 16. Zasada rozwoju kontraktu

Nowe dane mogą zostać dodane do kontraktu dopiero, gdy istnieją jako rzeczywiste i zwalidowane dane w `ventilation-core`.

AI Bridge nie definiuje danych z wyprzedzeniem i nie oczekuje, że CM5 dostarczy hipotetyczne wartości.

Źródłem prawdy pozostaje `ventilation-core`.

## 17. Nadrzędna decyzja

Dane przechodzą przez granicę systemu w kierunku:

```text
CoreState CM5
     ↓
snapshot telemetryczny
     ↓
AI Bridge RAW storage
     ↓
deterministyczne przygotowanie danych
     ↓
Qwen
     ↓
interpretacja / rekomendacja
```

Qwen oraz AI Bridge nie posiadają ścieżki sterującej z powrotem do CM5.
