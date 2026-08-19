# Qwen ventilation semantic benchmark

Powtarzalny benchmark jakości interpretacji aktywnego profilu Qwena w repozytorium AI Server.

## Cel

Benchmark nie mierzy wyłącznie szybkości modelu. Jego głównym celem jest sprawdzanie, czy po zmianie promptu, modelu albo parametrów inferencji Qwen nadal:

- poprawnie rozpoznaje istotne zdarzenia w pakiecie analitycznym,
- nie wymyśla progów, norm ani zewnętrznych standardów,
- nie zamienia `VOC Index` lub `NOx Index` na nieistniejące stężenia,
- nie wymyśla konkretnych czynności warsztatowych jako przyczyny,
- nie traktuje setpointu 0-10 V jak RPM albo przepływu,
- nie klasyfikuje samego trybu `STOP` i 0 V jako awarii, gdy oczekiwany stan pracy jest nieznany,
- właściwie zauważa problemy SENSOR BUS, jakość danych i alarmy sterownika,
- zwraca wynik zgodny z aktualnym `VentilationAnalysisResult` i Structured Output Ollamy.

Benchmark korzysta bezpośrednio z aktualnych elementów produkcyjnych:

- `SYSTEM_PROMPT`, `PROMPT_VERSION` i `ANALYSIS_THINK` z `analysis_profile.py`,
- `VentilationAnalysisResult` z `analysis/schemas.py`,
- `compact_schema_for_ollama()` i `OllamaClient.chat_structured()` z `ollama/client.py`,
- domyślnego modelu, URL Ollamy i temperatury z `Settings`.

Nie zmienia kodu produkcyjnego, promptu ani danych w PostgreSQL.

## Zestaw v1

Pierwsza wersja zawiera 10 scenariuszy:

1. stabilne kompletne dane bez baseline'u,
2. skok PM tylko na jednym SEN55,
3. zdarzenie VOC Index bez równoczesnego PM/NOx,
4. zdarzenie NOx Index,
5. zdegradowany pojedynczy węzeł SEN55,
6. STOP + 0 V przy nieznanym oczekiwanym stanie pracy,
7. awaria/niestabilność workera SENSOR BUS,
8. wysokie setpointy 0-10 V bez RPM i airflow,
9. całkowity brak VOC Index z jednego węzła,
10. `FAULT` sterownika z aktywnym alarmem.

Scenariusze są zapisane w `scenarios.json`. Każdy definiuje:

- nadpisania bazowego compact packetu,
- dopuszczalne statusy,
- wymagane elementy odpowiedzi (`must_match`),
- zabronione twierdzenia (`must_not_match`).

Dodatkowo runner stosuje wspólne zabezpieczenia przeciwko samowolnemu użyciu WHO, jednostek ppm/ppb oraz meta-ofert typu „mogę przygotować wykres”.

## Uruchomienie

Z katalogu głównego repozytorium, w aktywnym środowisku Pythona:

```bash
python benchmarks/qwen_ventilation/run.py --list
```

Najpierw warto wykonać walidację pakietów bez wywołania modelu:

```bash
python benchmarks/qwen_ventilation/run.py --dry-run > /tmp/qwen-benchmark-dry-run.json
```

Pełny benchmark v1:

```bash
python benchmarks/qwen_ventilation/run.py
```

Pojedynczy scenariusz:

```bash
python benchmarks/qwen_ventilation/run.py \
  --scenario pm_spike_single_node
```

Kilka wybranych scenariuszy:

```bash
python benchmarks/qwen_ventilation/run.py \
  --scenario stable_complete_no_baseline \
  --scenario high_setpoints_without_airflow_or_rpm
```

## Powtarzalność

Jedno uruchomienie służy jako smoke test. Przed zaakceptowaniem zmiany promptu lub konfiguracji uruchamiamy każdy scenariusz kilka razy, np.:

```bash
python benchmarks/qwen_ventilation/run.py --repeat 3
```

Zmiana jest kandydatem do przyjęcia dopiero wtedy, gdy nie pogarsza wyników istniejącego zestawu. FAIL nie oznacza automatycznie błędu promptu — może również wskazywać, że reguła benchmarku jest zbyt restrykcyjna i wymaga świadomej korekty.

## Thinking mode

Domyślnie benchmark używa `ANALYSIS_THINK` z aktualnego profilu produkcyjnego. Można wykonać kontrolne porównanie bez thinking:

```bash
python benchmarks/qwen_ventilation/run.py --no-think
```

Benchmark zapisuje w raporcie wartość `think`, temperaturę, model i wersję promptu, dzięki czemu wynik jest audytowalny.

## Raport

Każde pełne uruchomienie zapisuje JSON do:

```text
benchmark_results/qwen_ventilation/
```

Raport zawiera:

- wersję aktywnego promptu,
- model,
- tryb thinking,
- temperaturę,
- wynik PASS/FAIL każdego scenariusza,
- wszystkie wykonane checki,
- pełny structured result Qwena,
- surową zawartość odpowiedzi,
- `prompt_eval_count`, `eval_count` i `total_duration_seconds`,
- łączny pass rate.

Katalog wynikowy jest lokalnym artefaktem testowym i nie powinien trafiać do Git.

## Zasada rozwoju

Benchmark jest punktem odniesienia dla Semantic Hardening AI Servera. Najpierw zapisujemy scenariusz ujawniający problem, następnie zmieniamy prompt lub konfigurację, a potem uruchamiamy ponownie cały zestaw. Nie stroimy Qwena wyłącznie pod pojedynczą odpowiedź.
