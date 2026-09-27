# ADR-005 — Stage O.1 Technical Conversation Layer v1

**Data:** 2026-09-27  
**Status:** accepted for Stage O.1 candidate

## Kontekst

Discord ma być wyłącznie technicznym klientem AI Platform. Odpowiedzi mają korzystać
z Knowledge/ERS, źródeł i wspólnej polityki jakości, bez fallbacku do ogólnego
agenta Hermesa.

Jednocześnie planowany StackChan ma korzystać z tej samej rozmowy technicznej.
Logika retrieval, pamięć sesji i reguły bezpieczeństwa nie mogą należeć do
adaptera Discorda.

## Decyzja

AI Platform udostępnia wersjonowany kontrakt:

- `POST /api/v1/conversation/turn`
- `GET /api/v1/conversation/{conversation_id}`
- `technical_conversation_contract_version=1`

Conversation Layer przyjmuje identyfikator klienta, wiadomość, domenę i opcjonalny
`conversation_id`. Warstwa sama zarządza technicznym kontekstem sesji.
## Własność sesji

Historia rozmowy należy do AI Platform, nie do Discorda, Hermesa ani przyszłego
StackChana. W Stage O.1 retencja jest celowo ograniczona do runtime:

- maksymalnie 128 sesji,
- 12 turnów na sesję,
- brak migracji bazy w Stage O,
- restart Platformy może wyczyścić historię.

Trwała historia może zostać dodana później bez zmiany kontraktu klienta.

Discord wylicza nieodwracalny identyfikator sesji z kanału/threadu i przekazuje go
jako `conversation_id` oraz `context.session_id`. Surowe identyfikatory Discorda
nie trafiają do publicznego API.

## Contextualization

Samodzielne pytania pozostają niezmienione. Poprzednie pytanie jest dołączane do
retrieval tylko dla prawdopodobnych follow-upów, np. „A ile ma flashu?”.

Pytania zawierające własny identyfikator lub nazwę techniczną, np.
„Jaki SPN był przy naprawie Hatz?”, nie są zanieczyszczane poprzednim kontekstem.
## Retrieval quality

Stage O.1 wprowadza `technical-evidence-v2`.

Reranking i lexical search uwzględniają nie tylko treść chunka, ale również:

- tytuł dokumentu,
- URI źródła,
- `repository_path`,
- nazwę sekcji,
- literalne identyfikatory techniczne.

Dzięki temu dokument CASE/ECU może awansować nad ogólnie podobny manual nawet
wtedy, gdy nazwa ECU występuje w tytule lub ścieżce, a nie w każdym chunku.

## Grounding guard

Technical Conversation Layer wymaga minimalnego sygnału technicznego w retrieval.
Jeżeli wyniki są wyłącznie semantycznym szumem, odpowiedź kończy się jako
`insufficient_context` przed uruchomieniem LLM.

Bezpośredni kontrakt `/knowledge/ask` zachowuje dotychczasowe zachowanie; guard
jest obowiązkowy dla Conversation Layer.
## Klienci

### Discord

Discord jest pierwszym adapterem:

- text i voice -> `/conversation/turn`,
- źródła są wyświetlane w odpowiedzi tekstowej,
- TTS czyta odpowiedź bez URL-i,
- foto/wideo pozostają zablokowane,
- ogólny agent Hermesa pozostaje pominięty,
- Telegram zachowuje dotychczasową ścieżkę.

### StackChan

StackChan nie jest wdrażany fizycznie w Stage O.1. Następny klient ma używać
tego samego kontraktu Conversation Layer i może współdzielić `conversation_id`
z innym interfejsem, bez bezpośredniego dostępu do Knowledge backendu.

## Kryteria jakości Stage O.1

Gate ma potwierdzać co najmniej:

- Scania EMS S6 -> `MPC555LF8MZP40`,
- Hatz -> poprawny retrieval CASE-0001,
- cytowania Knowledge,
- brak general-agent fallbacku,
- blokadę Discord media,
- voice RAG/TTS,
- pytanie bez oparcia w domenie -> fail-closed przed LLM.
