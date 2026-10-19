# RM EXCLUSIVE — naprawa startu transient systemd (2026-10-19)

## Incydent próby
Użytkownik uruchomił `run_rm_systemd_exclusive_three_engine_dev.sh` o 22:33:39 CEST.
Próba: `attempt-20261019-203334-ZYXS7No3`, jednostka:
`ai-rm-p203334-229203-ollama.service`.

Start zakończył się przed wykonaniem programu Ollama:
`Failed at step STDIN spawning /usr/local/bin/ollama: Operation not permitted`
oraz `status=208/STDIN`. Systemd odnotował wynik `exit-code`.
Skrypt przerwał pracę w stanie DIRTY, nie wystartował ComfyUI ani Vision.
Uprzywilejowane zatrzymanie jednostki nie znalazło już obiektu
(systemd-run `--collect` usunął zakończoną jednostkę). KFD/fuser
pozostały bez widocznych właścicieli; brak rozpoznanych błędów MES/AMDGPU.

## Przyczyna
Jednostka miała `DevicePolicy=strict` z allowlistą wyłącznie dla
`/dev/kfd` i `/dev/dri/renderD128`. Strumień wejściowy
systemd-run uruchamiał proces z `StandardInput=null`, które wymaga
otwarcia urządzenia `/dev/null`. Przy `strict` bez oddzielnego
dopuszczenia pseudourządzenia cgroup odrzuca otwarcie; start kończy
się `208/STDIN`. Potwierdzenie hipotezy opiera się na logu z hosta
i udokumentowanej semantyce `DevicePolicy=strict|closed` oraz
`StandardInput=null` (systemd.resource-control(5) i systemd.exec(5)).
Nie wykonano jeszcze nowej próby z poprawką system-manager, dlatego
jest to diagnoza silnie wsparta mechanizmem, nie osobny sprzętowy PASS.

## Korekta
Dla transient workerów zastosowano `DevicePolicy=closed`.
Pozostaje dokładna allowlista **fizycznych GPU**
`DeviceAllow=/dev/kfd rw` i `DeviceAllow=/dev/dri/renderD128 rw`.
`closed` dopuszcza oprócz niej tylko standardowe pseudourządzenia
`/dev/null`, `/dev/zero`, `/dev/full`, `/dev/random`,
`/dev/urandom`. Nie dopuszcza automatycznie innych GPU czy dysków.
Uzupełniono testy offline o oczekiwaną politykę i zachowano
`NonApprovingSafetyAdapter` bez zmian.

Do obsługi dalszego błędu skrypt zapisuje ostatnie wpisy
`journalctl` swojej jednostki do `last-unit-journal.log`,
zanim `--collect` ją usunie. Nadal tylko operator/sudo może uruchomić
test; nie instalowano ani nie przełączano żadnych usług produkcyjnych.

## Wyniki i ograniczenia
- Analiza dziennika rzeczywistego systemd: `208/STDIN`, przed startem Ollama.
- Brak aktywnego workera GPU po błędzie: sprawdzony.
- Testy shell i CPU: po zmianie PASS, pełne liczby w dalszej regresji.
- **Powtórny systemd test na sprzęcie: NOT_RUN** przed kolejnym
  autoryzowanym uruchomieniem przez operatora.
- `GPU_REUSE_SAFE=NOT_VERIFIED`,
  `N1_REAL_GPU_GRANT=NOT_ADMITTED`.
- `/opt/ai-platform/current`, grupy, uprawnienia i sterownik bez zmian.

Jeżeli kolejna próba nie startuje, nie uruchamiać na ślepo kilku
następnych; odczytać lokalnie `summary.log` i
`last-unit-journal.log` oraz ocenić, czy unit nie ma aktywnych
potomków przed kolejnym testem.

## Regresja po korekcie
Uruchomiono pełny wybrany zestaw testów N1–N5, Gateway, OS boundary,
runtime pilot i EXCLUSIVE checker: **617/617 PASS**, exit 0.
Log na serwerze: /tmp/rm-stdin-fix-full-regression-20261019.log.
Nie uruchamiano ponownie jednostek systemowego systemd bez operatora.
