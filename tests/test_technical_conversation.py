from ai_bridge.platform.technical_conversation import TechnicalConversationStore


def response(answer="ok"):
    return {
        "answer": answer,
        "citations": [{"ref": "S1"}],
        "insufficient_context": False,
    }


def test_platform_owned_conversation_contextualizes_real_followups_only():
    store = TechnicalConversationStore(max_sessions=4, turns_per_session=8)

    first = store.prepare(
        conversation_id="conv_test",
        message="Jaki procesor jest w sterowniku Scania S6?",
    )
    assert first.retrieval_query == "Jaki procesor jest w sterowniku Scania S6?"
    store.add_turn(
        conversation_id=first.conversation_id,
        user_message="Jaki procesor jest w sterowniku Scania S6?",
        response=response("MPC555LF8MZP40"),
        client_id="discord",
        retrieval_query=first.retrieval_query,
    )

    followup = store.prepare(
        conversation_id="conv_test",
        message="A ile ma flashu?",
    )
    assert followup.previous_user_query == "Jaki procesor jest w sterowniku Scania S6?"
    assert "Kontekst poprzedniego pytania" in followup.retrieval_query
    assert "Scania S6" in followup.retrieval_query

    standalone = store.prepare(
        conversation_id="conv_test",
        message="Jaki SPN był przy naprawie Hatz?",
    )
    assert standalone.retrieval_query == "Jaki SPN był przy naprawie Hatz?"


def test_conversation_history_is_platform_scoped_and_bounded():
    store = TechnicalConversationStore(max_sessions=1, turns_per_session=4)
    prepared = store.prepare(conversation_id="conv_one", message="Pytanie techniczne")
    store.add_turn(
        conversation_id=prepared.conversation_id,
        user_message="Pytanie techniczne",
        response=response(),
        client_id="discord",
        retrieval_query=prepared.retrieval_query,
    )
    detail = store.get("conv_one")
    assert [turn["role"] for turn in detail["turns"]] == ["user", "assistant"]
    assert detail["turns"][0]["client_id"] == "discord"
    assert store.retention()["scope"] == "platform-runtime"

    store.prepare(conversation_id="conv_two", message="Nowa sesja")
    store.add_turn(
        conversation_id="conv_two",
        user_message="Nowa sesja",
        response=response(),
        client_id="stackchan",
        retrieval_query="Nowa sesja",
    )
    try:
        store.get("conv_one")
    except KeyError:
        pass
    else:
        raise AssertionError("oldest conversation should be evicted")
