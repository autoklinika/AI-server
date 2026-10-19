# AI Platform / RM — OS GPU access boundary (DEV, 2026-10-19)

## Ocena hosta i aktualny blokujący fakt

**N1 real GPU admission: BLOCKED.** Usługi AI są wyłączone, a KFD/fuser
nie wykazują bieżących posiadaczy, lecz to nie zapewnia wyłączności.

Rzeczywisty stan:
- Radeon 890M: `/dev/kfd` i `/dev/dri/renderD128` mają tryb
  `0660 root:render`, ACL daje też dostęp `gdm-greeter`.
- Grupa `render` obejmuje `harrypotter`, `ollama`, `ai-vision`.
- `ai-gateway`, `ai-bridge`, `ollama`, `comfyui` miały
  `DevicePolicy=auto`, `PrivateDevices=no`. Obecnie są zatrzymane.
- Użytkownik `harrypotter` faktycznie otworzył `/dev/kfd`
  (O_RDONLY, bez ioctl i bez obliczeń) spoza RM.
- W testowej usłudze **użytkownikowego** systemd na Ubuntu 26.04/systemd
  259, `DevicePolicy=closed` ORAZ oddzielnie `DevicePolicy=strict`
  nie zablokowały otwarcia KFD. Oba testy zwróciły
  `UNEXPECTED_ALLOWED` / `STRICT_KFD_ACCESS=OPEN`.
- `PrivateDevices=yes` w tym samym user-manager nie uruchomił procesu:
  `status=218/CAPABILITIES`. Nie jest to pozytywny dowód device sandbox.
- Systemowy, root-owned `ai-vision-gpu-observer` ma
  `DevicePolicy=closed`, lecz jest **wyłącznie obserwatorem**; nie
  przejmuje uprawnień do GPU ani nie blokuje cudzych procesów.
- `enforce_isolation` sysfs ma wartość 0; nie zmieniano go.

Wniosek: **nie wolno odblokować N1 przez same `DevicePolicy` zapisane
w pliku ani przez puste odczyty KFD**.

## Kod bramki i testy

`src/ai_bridge/gateway/os_gpu_boundary.py`:
- czyta identyfikator PCI, stan usług AI i faktyczną próbę open/close
  obu urządzeń bez ioctl/compute;
- raportuje jawnie bypass, nieznany dostęp, nieaktywną produkcję oraz
  obecność jednostki workera;
- zawsze zwraca `decision=BLOCKED`, `driver_reuse=NOT_VERIFIED`,
  nawet przy negatywnym `open` aktualnego użytkownika, ponieważ
  ten pojedynczy proces nie reprezentuje wszystkich klientów GPU;
- nie ma interfejsu do `N1.can_start`, `N1.verify`, `release`
  ani żadnego mechanizmu zmiany production.

`tests/test_os_gpu_boundary.py`: testy CPU/mock fail-closed dla bypassu,
pozornie poprawnych usług, unknown, błędnej tożsamości, odmowy otwarcia
tylko jednej roli oraz systemd timer.

## Zachowujemy istniejący punkt OS-egzekwowania

Nie instalować drugiego obserwatora, brokera ani schedulera.
Istniejąca kandydacka jednostka:
`deploy/vision-rm-security/rooted/ai-vision-execution@.service.rocm`
w `vision-rm-system-security-worktree`, z `PrivateDevices=yes`,
`DevicePolicy=strict`, jawnie dopuszczonymi dwoma węzłami GPU,
`KillMode=control-group` oraz root-supervised launcherem.
NIE jest obecnie zainstalowana ani zatwierdzona. Stary bundle instalacji
obejmował tylko CPU. Nie importować wprost user-writable checkoutu
do root TCB i nie łączyć tego profilu z legacy produkcją.

## Następna bramka: system-manager cgroup device denial (root)

Potrzebny rzeczywisty **negatywny** i **pozytywny** test na tej samej
maszynie/wersji kernela, w osobnej transient unit systemd, z
`User=ai-vision` i widocznymi ścieżkami /dev (PrivateDevices=no).
Nie testujemy usługi użytkownikowej. Test negatywny wymaga:
`DevicePolicy=strict`, **bez** DeviceAllow, uruchomienia procesu
bez uprawnień administratora, a `open(/dev/kfd)` i
`open(/dev/dri/renderD128)` muszą zwrócić EPERM/EACCES, nie ENOENT.
Test pozytywny musi na tej samej konfiguracji po dopisaniu tylko tych
dwóch `DeviceAllow=... rw` móc otworzyć oba pliki. Bez CUDA/HIP
i bez ioctli. Jeśli którykolwiek wynik nie odpowiada oczekiwaniu:
STOP, `OS_ENFORCEMENT=FAIL`. Zachować `journalctl` dla obu jednostek i dane z procesu. Jednostki
transient z `--collect` nie gwarantują dostępności `systemctl show` po wykonaniu.
Przed testem sprawdzić zatrzymanie Ollama/ComfyUI, kernel bez
MES timeout, istniejące backupy/DR. Po teście nie zmieniać konfiguracji
produkcji.

Przykładowe dokładne polecenia operatora (uruchamiane jako interaktywny
root w serwerowym terminalu; nie z user-writable script):

Negatywny test:

```bash
sudo systemd-run --system --wait --collect --pipe \
  --unit=ai-rm-os-kfd-deny-v1 \
  -p User=ai-vision -p Group=ai-vision-rm \
  -p DevicePolicy=strict -p PrivateDevices=no \
  /usr/bin/python3 -I -S -c 'import os,errno
print("IDENTITY",os.geteuid(),open("/proc/self/cgroup").read().strip())
for p in ("/dev/kfd","/dev/dri/renderD128"):
 try:
  fd=os.open(p,os.O_RDONLY|os.O_CLOEXEC)
 except OSError as e:
  if e.errno not in (errno.EPERM,errno.EACCES): raise SystemExit(4)
  print("DENIED_AS_REQUIRED",p,e.errno)
 else:
  os.close(fd)
  raise SystemExit(3)'
```

Pozytywny test (dopiero jeśli negatywny był PASS):

```bash
sudo systemd-run --system --wait --collect --pipe \
  --unit=ai-rm-os-kfd-allow-v1 \
  -p User=ai-vision -p Group=ai-vision-rm \
  -p DevicePolicy=strict -p PrivateDevices=no \
  -p 'DeviceAllow=/dev/kfd rw' \
  -p 'DeviceAllow=/dev/dri/renderD128 rw' \
  /usr/bin/python3 -I -S -c 'import os
print("IDENTITY",os.geteuid(),open("/proc/self/cgroup").read().strip())
for p in ("/dev/kfd","/dev/dri/renderD128"):
 fd=os.open(p,os.O_RDONLY|os.O_CLOEXEC)
 os.close(fd)
 print("ALLOWED_AS_REQUIRED",p)'
```

Uwaga: To test ograniczenia **wyłącznie danej usługi systemowej**.
Nie dowodzi, że sesja `harrypotter`, desktop `gdm-greeter`, inne UID
w grupie `render` czy root nie mogą omijać RM.
Ten drugi problem wymaga osobnej polityki hosta i przeglądu
wpływu na graficzną sesję oraz ComfyUI/Ollama, zanim zmienimy
ACL/grupy/udev. Nie zmieniać w ciemno `render` lub `video`.

## Dopuszczenie N1

Nawet PASS obu systemd probes nie jest `GPU_REUSE_SAFE`.
N1 może przyznać rzeczywisty grant dopiero po ochronie wszystkich
ścieżek GPU submit, aktywnej bramce urządzenia dla zatwierdzonego
workera, identyfikacji generation/UID/PID/boot/cgroup, atomowym
przypisaniu ownership i niezależnej weryfikacji driver teardown.
Zachować `NonApprovingSafetyAdapter` do zamknięcia tych warunków.
