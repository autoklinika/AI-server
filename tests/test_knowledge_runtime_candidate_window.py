import pytest

from ai_bridge.knowledge.runtime import KnowledgeRuntime
from ai_bridge.providers.contracts import KnowledgeQuery, KnowledgeSearchResult


class FakeService:
    def __init__(self):
        self.limits = []

    def search(self, query):
        self.limits.append(query.limit)
        return KnowledgeSearchResult(
            request_id=query.request_id,
            results=(),
            backend="fake",
        )


class FakeReranker:
    def rerank(self, query, results, *, limit):
        return results


def runtime():
    value = object.__new__(KnowledgeRuntime)
    value.service = FakeService()
    value.reranker = FakeReranker()
    return value


@pytest.mark.parametrize(("requested", "candidate"), ((8, 40), (10, 40), (25, 100)))
def test_rerank_candidate_window_has_safe_floor_and_cap(requested, candidate):
    value = runtime()
    query = KnowledgeQuery(
        request_id="candidate-window",
        domain="ecu-repair",
        query="24LC16B I2C EEPROM addressing",
        limit=requested,
    )
    value.search(query, rerank=True)
    assert value.service.limits == [candidate]


def test_no_rerank_preserves_requested_limit():
    value = runtime()
    query = KnowledgeQuery(
        request_id="candidate-window-raw",
        domain="ecu-repair",
        query="24LC16B",
        limit=8,
    )
    value.search(query, rerank=False)
    assert value.service.limits == [8]
