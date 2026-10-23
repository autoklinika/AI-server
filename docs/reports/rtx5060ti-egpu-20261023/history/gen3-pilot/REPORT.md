# Raport wykonania

- PASS: przygotowano plan oraz preflight, 178 linii gen3_pilot.py.
- PASS: 15 testów unittest na fake sysfs i mocked setpci/geteuid.
- READY_FOR_MAINTENANCE_BOOT: gotowość procedury diagnostycznej, nie zapisów PCI.
- NOT_READY: aktualny boot nie ma parametrów maintenance; inspect zakończone kodem 2.
- BLOCKED: apply celowo niedostępne. Niepotwierdzone zachowanie rzeczywistego initramfs/jawnych loaderów i powiązanie tunelu PCI z routerem USB4. Wariant tylko plan/preflight zgodnie z dopuszczeniem użytkownika.
- NOT_VERIFIED / NOT REAL_GPU_VERIFIED: Gen3, retrain, manual driver load, CUDA, rollback i skuteczność maintenance boot nie były testowane na sprzęcie.

Odczytane fakty:

- host: harrypotter-AI-Series
- boot_id: `010ee19d-1cc5-4ae6-8d14-b03cd1a69dac`
- system: Ubuntu 26.04.1 LTS, kernel `7.0.0-39-generic`
- /sys/module/nvidia/version: `615.71.09`
- załadowane: nvidia, nvidia_uvm, nvidia_modeset, nvidia_drm, snd_hda_intel
- GPU obecnie 0000:03:00.0 związane z nvidia; bezpośredni rodzic 0000:02:00.0
- oba końce aktualnie 2.5 GT/s x4 według sysfs
- router TBGAA authorized=1, rx i tx 20.0 Gb/s × 2 lanes
- router UUID: ba7e8780-0065-ebf9-ffff-ffffffffffff
- setpci dostępne pod /usr/bin/setpci; nie wywołano realnego setpci nawet do odczytu

BDF są wyłącznie obserwacją, nie konfiguracją skryptu. Rzeczywisty wynik inspect
zapisano w preflight.json. Nie wykonywano sudo, modprobe, nvidia-smi, CUDA,
reboot, zmian usług, GRUB/dracut, zapisów PCI ani zmian produkcji. Nowe pliki
utworzono wyłącznie w bieżącym katalogu. Nie odczytywano zegara do raportu;
nie przypisujemy wymyślonego czasu pomiarom.
