"""User-facing response language policy for AI Platform."""

POLISH_RESPONSE_POLICY = (
    "Odpowiadaj użytkownikowi po polsku. "
    "Wszystkie wyjaśnienia, opisy, wnioski, ostrzeżenia i zalecenia mają być po polsku, "
    "niezależnie od języka pytania lub materiałów źródłowych. "
    "Zachowuj bez tłumaczenia identyfikatory techniczne, nazwy pól JSON, kody błędów, "
    "DTC, nazwy własne, fragmenty kodu i dosłowne cytaty ze źródeł. "
    "W odpowiedziach strukturalnych tłumacz na polski naturalnojęzykowe wartości tekstowe, "
    "ale nie zmieniaj kluczy ani wartości o znaczeniu kontraktowym."
)


def apply_polish_response_policy(messages: list[dict[str, str]]) -> list[dict[str, str]]:
    """Return a copy of messages with a mandatory Polish user-facing language rule."""
    copied = [dict(message) for message in messages]
    for index, message in enumerate(copied):
        if message.get("role") == "system":
            copied[index]["content"] = message["content"].rstrip() + "\n\n" + POLISH_RESPONSE_POLICY
            return copied
    return [{"role": "system", "content": POLISH_RESPONSE_POLICY}, *copied]
