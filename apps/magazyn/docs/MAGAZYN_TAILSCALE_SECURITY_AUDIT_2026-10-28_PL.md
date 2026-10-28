# Magazyn V1 / AI Platform — audyt Tailscale

**Data:** 28 października 2026. **Host:** rzeczywisty serwer produkcyjny.
**Tryb:** wyłącznie odczyt, bez zmian ACL, Tailscale Serve, UFW ani usług.
**Wynik segmentacji sieci pracownika:** **FAIL — HIGH**.

## Metodyka i zakres

Wykonano na żywym serwerze: tailscale status --json, tailscale debug netmap, tailscale get --json all, tailscale serve status --json, tailscale funnel status, ss -lnt, sprawdzenie UFW/systemd i anonimowe HTTPS GET. Rozpoznano odbierany przez hosta efektywny PacketFilter. Pełna sieciowa mapa nie została opublikowana, ponieważ zawiera szczegóły węzłów/kluczy. Zapisano wyłącznie zanonimizowane podsumowanie JSON na serwerze w katalogu prywatnym: /srv/ai-data/magazyn-v1/reports/tailscale-audit-20261028-sanitized.json (0600).

Centralnego pliku polityki ACL/Grants z panelu administratora Tailscale nie udało się odczytać bez centralnej sesji lub klucza API tylko do odczytu. Nie było potrzeby uzyskiwania uprawnień administracyjnych, aby udowodnić, że lokalne efektywne reguły Tailscale nie zapewniają segmentacji do 8443.

## Potwierdzone ustalenia

- Tailscale 1.102.4, status Running. Tailscale netfilter-mode=on, shields-up=false.
- Tailscale Serve HTTPS 8443 → 127.0.0.1:18765 (Magazyn produkcyjny), wyłącznie tailnet; działające TLS, GET /healthz HTTP 200.
- Tailscale Serve HTTPS 443 → wewnętrzny panel AI Platform /control, wyłącznie tailnet.
- Funnel publiczny: nie stwierdzono, oba endpointy opisane jako tailnet only.
- **KRYTYCZNA NIEZGODNOŚĆ Z ZAŁOŻENIEM:** mapa Tailscale ma tylko **jedną regułę PacketFilter**, z destination 0.0.0.0/0 i ::/0, porty od 0 do 65535, protokoły TCP, UDP i ICMP. Jej zakresy source pokrywają prawie całą pulę Tailscale IPv4 oraz odpowiedni prefiks IPv6. Brak egzekwowanego ograniczenia tylko do tcp/8443 po stronie Tailscale serwera.
- Widoczne 9 peerów, z których **wszystkie 9** należą do dozwolonych zakresów źródłowych tej reguły. Jeden peer oznaczony jest jako współdzielony (ShareeNode=true) i także pasuje. Dla ochrony prywatności nie ujawniano identyfikatorów ani maili. Nie dowiedziono, że konkretny oznaczony węzeł należy do pracownika.
- OpenSSH nasłuchuje na wszystkich interfejsach IPv4 i IPv6: port 22. Wyłączenie funkcji Tailscale SSH nie wyłącza zwykłego OpenSSH.
- Cockpit nasłuchuje na wszystkich interfejsach: port 9090.
- Inne listenery Tailscale: 51907 i 57629. Ich przeznaczenie i dostęp z zewnątrz nie zostały zbadane.
- Brama AI 8080 słucha na adresie LAN, a nie na adresie interfejsu Tailscale; nie należy utożsamiać tego z bezpośrednim zdalnym dostępem przez tailnet.
- Funkcja Tailscale SSH=false; exit-node=false; advertise-routes puste; accept-routes=false.
- Usługa UFW systemd active. Polecenia odczytu jej reguł UFW i nft wymagają uprawnień sudo, których brak w obecnej sesji. **NIE POTWIERDZONO** realnej polityki kernela; dodatkowy firewall może blokować 22/9090/443 mimo zbyt szerokiej reguły Tailscale.
- Właściciel potwierdził na telefonie pracownika: 8443 DZIAŁA, panel /control na 443 NIE OTWIERA SIĘ. Nie potwierdzono przyczyny odmowy, nie jest to test TCP i nie zastępuje audytu ACL.
- Produkcyjne usługi Magazynu i Telegrama działają. Audyt ich nie restartował i nie modyfikował.

## Ryzyko

Udostępnienie konkretnej maszyny innej osobie ogranicza zakres do tej maszyny, **ale nie zapewnia automatycznie ograniczenia jej portów**. Jeżeli inne warstwy nie blokują ruchu, szeroki PacketFilter może pozwalać na próby połączenia z SSH 22, konsolą Cockpit 9090, panelem AI Platform 443 i pozostałymi usługami tego samego hosta. Loginy SSH, Cockpit i aplikacji nadal chronią swoje zasoby, ale celem projektu jest wcześniejsze odcięcie nieautoryzowanego ruchu w Tailscale.

Nie potwierdzono uzyskania nieautoryzowanego dostępu ani rzeczywistego połączenia pracownika do innych portów. Wynik **FAIL** oznacza brak weryfikowalnej, wymaganej segmentacji na tym serwerze.

## Rekomendowane działania (nie wykonano)

1. Właściciel otwiera Tailscale Admin Console → Access controls → JSON policy oraz Preview rules. Należy odczytać **całą aktualną politykę**, nie tylko dopisać jedną regułę.
2. Zweryfikować broad allow-all: czy istnieje ACL ze źródłem gwiazdka i destination wszystko/każdy port, czy grant z src/dst/ip gwiazdka lub brak ACL powodujący domyślny allow-all. **Reguły grant są addytywne: nowa restrykcyjna reguła sama nie usunie starego szerokiego pozwolenia.**
3. Zachować pełny, konieczny dostęp właściciela do własnych urządzeń oraz potrzebne połączenia Platformy.
4. Ograniczyć **konkretną tożsamość Tailscale pracownika** do hosta AI Server, protokół TCP, port 8443. Schemat przykładowego POJEDYNCZEGO grantu do dopasowania do istniejącej polityki:

    {
      "src": ["TOZSAMOSC_TAILSCALE_PRACOWNIKA"],
      "dst": ["TAILSCALE_IP_AI_SERVER"],
      "ip": ["tcp:8443"]
    }

   Nie jest to gotowa kompletna polityka. Jeśli ogólny allow-all nadal obejmuje pracownika, bezpieczeństwo nie poprawi się. Alternatywnie można użyć autogroup:shared, ale przy jednym pracowniku precyzyjne wskazanie tożsamości daje lepszą kontrolę.
5. W Preview rules i Tests zdefiniować asercje dla pracownika: **ALLOW tcp/8443**, **DENY tcp/443, tcp/22, tcp/9090** oraz innych portów. Dodatkowo sprawdzić, że właściciel zachowuje dostęp do 443, SSH i wszystkich potrzebnych systemów.
6. Po zmianie polityki ponownie zweryfikować effective PacketFilter na serwerze i wykonać rzeczywiste testy portów z urządzenia pracownika, a nie tylko otwieranie adresów w przeglądarce.
7. Osobno, jako osoba uprawniona, zweryfikować reguły UFW (np. sudo ufw status verbose i sudo nft list ruleset), bez restartowania czy resetowania firewalla.

Bez dostępu do istniejącego centralnego pliku polityki **nie wprowadzamy zmian**, ponieważ mogłyby odciąć administratora, serwer lub inne urządzenia Platformy.

## Stan bramki produkcyjnej

**employee_access: BLOCKED / NO_GO.** Produkcja Magazynu nadal działa na wyraźne życzenie właściciela z udokumentowanym wyjątkiem bezpieczeństwa. Odrębną niezamkniętą kwestią pozostaje drugi YubiKey 5C do niezależnego odzyskiwania.

## Dokumentacja Tailscale

- https://tailscale.com/docs/features/sharing
- https://tailscale.com/docs/features/access-control
- https://tailscale.com/docs/features/access-control/grants
- https://tailscale.com/docs/features/tailnet-policy-file/manage-tailnet-policies
- https://tailscale.com/docs/reference/visual-editor
- https://tailscale.com/docs/features/tailscale-serve

## Dodatkowe kontrole urządzeń i tożsamości

- Konto Tailscale serwera ma ważny klucz urządzenia; termin wygaśnięcia za około 129 dni. Brak bieżącego wygaśnięcia klucza hosta.
- Wśród dziewięciu widocznych peerów trzy mają oznaczenie wygasłego klucza. Nie przypisywano ich pracownikowi; porządki w nieużywanych urządzeniach należy wykonać dopiero po weryfikacji właściciela.
- Urządzenie udostępnione innej sieci: jeden peer ze znacznikiem ShareeNode jest online; jest objęty szerokim zakresem reguły PacketFilter. Potwierdza to realny problem dla co najmniej jednej udostępnionej tożsamości, choć nie ujawnia ani nie dowodzi nazwy pracownika.
- MagicDNS aktywny. Brak tagów na samym serwerze. Mechanizm Tailnet Lock nie został włączony — dodatkowa opcja bezpieczeństwa, niezależna od aktualnej niezgodności portów, nie jest wymagana do jej naprawy.
- W Tailscale SSH policy nie ma reguł, a lokalny przełącznik Tailscale SSH jest wyłączony. Zwykły sshd na 22 nadal nasłuchuje, więc wymaga osobnej ochrony.
