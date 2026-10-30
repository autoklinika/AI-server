# Granite 4.0 1B — prace DEV podczas oczekiwania na eksport rozmów

**2026-10-26 | Serwer AI | PR #182 | tylko DEV, bez produkcyjnego cutover**

## Wyniki

Na serwerze `harrypotter-AI-Series` wykonano nową, prywatną serię **34 świeżo sformułowanych przypadków redakcyjnych**, odseparowaną od istniejących zestawów zamrożonych 120, diagnostycznych 24 i cytatów użytkownika 68. Każdy przypadek uruchomiono przez tymczasowy Gateway HTTP DEV (loopback), korzystający z **globalnego Resource Managera i RTX Ollama** z `granite-router-v4-tpl1:dev`.

| Kategoria | Zgodne z oczekiwaniami redakcyjnymi | Błędy kontraktu |
|---|---:|---:|
| `no_action` — zakończenie bez zadania | 8/8 | 0 |
| `clarify` — brak niezbędnego kontekstu | 8/8 | 0 |
| `fallback` — wymagany web/GitHub/host | 8/8 | 0 |
| `route` — wiedza, reasoning, graf, WVC, ERS | 10/10 | 0 |
| **Razem** | **34/34** | **0** |

Wynik **nie jest GOLD**, nie jest miarą dokładności na niezależnych pytaniach, nie obejmuje prawdziwych załączników obrazowych ani długich rozmów. Etykiety zostały przygotowane redakcyjnie razem z testem. Dane nie mogą być potem promowane do finalnego holdoutu ani użyte do bieżącego treningu.

Dla testu: `/srv/ai-data/staging/granite-router-gguf-dev-20261026/run_fresh_silver_policy_diagnostic.py`. Prywatny wynik i manifest: `granite_v4_fresh_policy_challenge_20261026.jsonl` oraz `granite_v4_fresh_policy_challenge_report.json`.

SHA256 raportowanych 34 wyników: `c17b6e857c914074a2168f6b3a1efea4c551392228a372e65f401a0bec258cdf`.

## Bezpieczeństwo

Wprowadzono niezależną serię regresji `tests/test_granite_preview_fault_safety.py`:

- **RM zajęty:** Granite nie może zarezerwować GPU i nie wysyła żądania do Ollamy.
- **Niepoprawne JSON / brak wymaganych pól / sprzeczna capability:** twarda odmowa; brak wykonania narzędzi.
- **Ollama 503 / brak `message`:** żądanie kończy się błędem; po weryfikacji wyładowania GPU lease jest zwalniany z terminalnym statusem `failed`.
- Wymuszone generowanie schema pozostaje usunięte; walidator `parse_router_decision` nadal jest obowiązkowy.

Testy powyższe są **mockowane i nie zastępują pełnych prób awaryjnych na rzeczywistym GPU**. Faktyczne 34 inferencje na RTX zweryfikowały wydawanie i zwalnianie globalnych leases oraz brak rezydentów po każdym przypadku. Tymczasowy Gateway DEV został zatrzymany po serii.

## Decyzje

1. Pozostawić aktywny tylko model DEV `granite-router-v4-tpl1:dev` w istniejącej Ollamie, lecz nie załadowany do VRAM i bez automatycznego routingu.
2. **Nie uruchamiać treningu v5 na dotychczasowych benchmarkach lub realnych cytatach.** Zbiór GOLD z eksportu rozmów musi być niezależny od danych treningowych, diagnostycznych i kalibracyjnych.
3. Podczas oczekiwania na eksport można rozwijać kontrolę skrajnych przypadków, testy przeciążenia i bezpieczne integracje WebGUI, ale bez nowych usług/koordynatorów i bez zmian w produkcji.
4. Nie nadawać nowym pytaniom syntetycznym etykiety `human_gold`, nie publikować prywatnych danych na GitHub i nie scalać PR #182 jako gotowego routingu produkcyjnego.

**Brama odbioru:** `SILVER_DIAGNOSTIC_PASS`, `RM_GPU_CLEANUP_PASS`, `PRODUCTION_ROUTING_DISABLED`, `INDEPENDENT_GOLD_STILL_PENDING`.
