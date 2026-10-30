# GitHub + Codex Cloud — proces rozwoju AI Platform / RM

Status: przygotowanie repozytorium do rozwoju w chmurze. P1 jest pakietem CPU-only; P2 pozostaje niewdrożony. Produkcja — **NO-GO**.

## Środowisko Codex Cloud

Repozytorium: `autoklinika/AI-server`; gałąź bazowa: `main`.
To repozytorium jest publiczne. W cloud environment **nie** udostępniamy kluczy, certyfikatów, tokenów, połączeń Tailscale, dostępu SSH do Minisforum ani danych produkcyjnych.

W interfejsie Codex Cloud (web lub aplikacja desktopowa):
1. Połącz konto GitHub mające dostęp do `autoklinika/AI-server`.
2. Utwórz środowisko dla tego repozytorium z Python 3.12 lub 3.14, bez GPU i bez usług lokalnych.
3. Jako krok przygotowania wykonaj `bash .codex/cloud-setup.sh`. Sprawdź środowisko i je opublikuj.
4. W nowych zadaniach wybierz opublikowane środowisko, najwyższy dostępny model/poziom rozumowania oraz izolowaną gałąź.
5. Każde zadanie kończy się commitem/PR. Stan niezatwierdzonej maszyny zadaniowej nie zastępuje Git.

Publikowanie środowiska i włączenie Code Review w osobistym koncie Codex wymaga użytkownika w interfejsie Codex; sam dostęp GitHub z ChatGPT nie oznacza automatycznie, że środowisko Codex Cloud jest połączone.

## Proces PR

- Jedno zadanie lub jeden mały pakiet na jedną gałąź. Bez bezpośrednich zmian w `main`.
- Codex implementuje kod i uruchamia testy CPU-only.
- GitHub Actions sprawdza Python 3.12 i 3.14, istniejące kontrakty RM, Ruff oraz mypy.
- Osobny przebieg Codex Code Review ocenia diff i zgodność z `AGENTS.md`. Po włączeniu integracji można wywołać `@codex review` w komentarzu PR.
- Zmiany z uwagami HIGH/CRITICAL nie są scalane; poprawka wymaga nowego testu regresyjnego.
- Człowiek zatwierdza merge dopiero po zielonych testach i przeglądzie. Merge sam w sobie **nie** wdraża nic na Minisforum.
- Testy GPU/eGPU i kontrolowane wdrożenie przeprowadzane są osobno, po audycie zmian i zgodzie na wydanie.

CI jest planistycznie rozdzielone od produkcji: GitHub-hosted runner nie ma dostępu do serwera. Nie instalujemy self-hosted GitHub Actions Runner na Minisforum.

## P1 — stan odniesienia

Pakiet P1 zawiera `resource_topology.py`, `resource_accounting.py`, oryginalne oraz niezależne testy i kontrakt. Historyczny lokalny odbiór: 317 testów PASS, Ruff i strict mypy PASS w izolowanym środowisku DEV. W GitHubie wymagane są **nowe** wyniki CI; wyniku lokalnego nie wolno przedstawiać jako wyniku GH.

Nie kopiowano kodu z GPUStack, LocalAI i Lemonade. P1 jest kalkulatorem bez uprawnienia do rezerwacji. Brak zaufanego discovery i atomowej integracji P2; production NO-GO.

## Zadanie P2 dla Codex Cloud — pierwsza iteracja

**P2-A: Shadow resource accounting, bez żadnych nowych przydziałów.**

Cel: podłączyć do istniejącego Gateway/RM jedynie obserwacyjną ocenę dopasowania P1 przy zaufanych, jawnie mockowanych wejściach w testach. Nie wolno zmieniać decyzji istniejącego schedulera, uruchamiać/wyładowywać modeli ani wpływać na `GPU_REUSE_SAFE`.

Warunki odbioru:
- Stary interfejs, kolejka, rezerwacje i lifecycle pozostają nietknięte semantycznie.
- Obserwacyjna ścieżka jest domyślnie wyłączona i nie może przydzielać zasobów ani wpływać na status produkcyjny.
- Porównywane wyniki mają rozróżnienie `FIT` / `DENY` / `UNKNOWN` i nie udają autoryzacji.
- Brak wiarygodnej tożsamości GPU, gen/revision lub telemetrii oznacza `UNKNOWN`/odmowę — nie zgadywanie.
- Dwa RTX są oddzielne; Radeon UMA współdzieli RAM hosta.
- Testy CPU/mock obejmują anulowanie, missing/stale telemetry, niezgodne generacje, izolowane awarie i niezmieniony stary RM.
- Bez nowego schedulera, bez zadań w tle, bez zmiany systemd, bez działań w sieci prywatnej, bez produkcyjnego GO.

Po P2-A i osobnej recenzji: P2-B atomowa rezerwacja w **istniejącym** RM, P2-C wiarygodne potwierdzanie cleanupu i kwarantanna. To oddzielne PR-y i odbiory, nie jeden ogromny diff.

## Bezpieczeństwo repozytorium

Do publicznego GitHub nie commitujemy plików .env, lokalnych logów, dumps, kluczy, plików z domowego katalogu użytkownika ani wartości poświadczeń. Sprawdzamy dokładny zestaw plików przez `git diff --cached --name-only` i skan tekstowy przed push. Każdy CI job ma token GitHub `contents: read`, a action dependencies są przypięte do commit SHA.

Wymagany warunek odbioru przeniesienia: GitHub PR rzeczywiście istnieje, zawiera tylko zatwierdzone pliki, workflow startuje w GH, a wynik sprawdzamy na rzeczywistych runach. Nie twierdzimy, że Codex Cloud jest skonfigurowany, dopóki środowisko nie zostanie utworzone i opublikowane w koncie użytkownika.
