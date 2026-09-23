# Stage J — Knowledge Service / Qdrant foundation

## Cel

Uruchomić pierwszy retrieval backend bez związania platformy z produktem Qdrant.
Qdrant jest prywatnym indeksem Knowledge Service i nie jest source of truth.

## Deployment baseline

- image: Qdrant `v1.19.1`, przypięty również digestem obrazu;
- REST: `127.0.0.1:6333`;
- gRPC: `127.0.0.1:6334`;
- cluster port 6335 nie jest publikowany;
- storage: `/srv/ai-data/qdrant/storage`;
- producent telemetry: disabled;
- publiczni klienci nie łączą się z tymi portami.

## Start

Na AI Server źródłem wykonywalnego deploymentu jest idempotentny wrapper:

```bash
deploy/stage-j/qdrant_runtime.sh start
```

Manifest `docker-compose.qdrant.yml` pozostaje równoważnym, przenośnym desired state
dla hostów posiadających Docker Compose. Bieżący AI Server nie wymaga Compose.
## Smoke

```bash
deploy/stage-j/qdrant_runtime.sh smoke
```

Smoke tworzy tymczasową kolekcję 3D, zapisuje jeden fragment ze źródłem,
wykonuje wyszukiwanie przez `KnowledgeService -> QdrantKnowledgeBackend`,
sprawdza source attribution i usuwa kolekcję w `finally`.

## Stop

```bash
deploy/stage-j/qdrant_runtime.sh stop
```

Stop nie usuwa danych z `/srv/ai-data/qdrant/storage`.

## Ważne

Produkcyjna kolekcja nie jest tworzona na tym etapie. Jej wymiary i konfiguracja
zależą od wyboru embedding modelu i wyników benchmarku ECU/WVC.
Exact/keyword/full hybrid będą dodawane jako jawne capability, bez ukrytych fallbacków.
