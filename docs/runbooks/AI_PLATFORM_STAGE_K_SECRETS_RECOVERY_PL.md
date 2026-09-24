# AI Platform — Stage K Secrets Recovery Runbook

## Cel

Ten runbook opisuje odzyskanie sekretów z zaszyfrowanego bundle Stage K bez przechowywania prywatnego klucza na AI Serverze lub GlobalNAS.

Encrypted bundle znajduje się pod `AI_Platform/Platform/secrets/<tier>/<backup_id>/secrets.tar.gz.age`.

Prywatny klucz recovery jest kluczem SSH Ed25519 odpowiadającym fingerprintowi zapisanym w `manifest.json`. Dla pierwszego recovery setu fingerprint to `SHA256:BVPwRUzB0IbP/6QVNsy9/XbIxs8MxHxbvFJ6soFNUPM`.

## Zasady bezpieczeństwa

- Nie kopiuj prywatnego klucza recovery na produkcyjny AI Server.
- Nie przechowuj odszyfrowanego archiwum na GlobalNAS.
- Przed odszyfrowaniem zweryfikuj `manifest.sha256`, SHA-256 bundle i fingerprint recipienta.
- Odszyfrowuj wyłącznie na zaufanym recovery workstation posiadającym prywatny klucz.
- Restore wykonuj dopiero na przygotowanym replacement/recovery host.

## Weryfikacja przed decrypt

Na AI Serverze lub recovery host uruchom:

```bash
python3 deploy/stage-k/k3_secrets_verify.py /mnt/AI_Platform/Platform/secrets/<tier>/<backup_id>
```

Wynik musi mieć `status=PASS`.

## Decrypt test na recovery workstation

Zainstaluj `age`, a następnie użyj prywatnego klucza SSH odpowiadającego recipientowi:

```bash
age -d -i ~/.ssh/id_ed25519_ai_server \
  -o /tmp/stage-k-secrets.tar.gz \
  secrets.tar.gz.age

tar -tzf /tmp/stage-k-secrets.tar.gz
```

Lista musi zawierać tylko oczekiwane ścieżki recovery.

Po kontroli usuń plaintext:

```bash
rm -f /tmp/stage-k-secrets.tar.gz
```

## Preferowany restore bez plaintextowego archiwum

Na finalnym replacement host preferowany jest streaming decrypt bez zapisywania plaintext tar:

```bash
age -d -i ~/.ssh/id_ed25519_ai_server secrets.tar.gz.age | \
  ssh <recovery-host> 'sudo tar -xzf - -C /'
```

Przed wykonaniem takiego restore należy sprawdzić listę plików, docelowe owner/mode oraz zatrzymać usługi korzystające z przywracanych sekretów.

Po restore wymagane jest:
- właściciel i uprawnienia zgodne z manifestem/procedurą;
- `systemctl daemon-reload`, jeżeli zmieniono konfigurację usług;
- restart tylko usług wymagających przywróconych sekretów;
- health check AI Bridge, AI Gateway, Hermes i dostępu do GlobalNAS;
- brak sekretów w logach i historii shell.

## K5

K5 ma wykonać rzeczywisty decrypt/restore drill na zewnętrznym recovery workstation lub replacement-host. Nie wykonujemy self-decrypt na produkcyjnym AI Serverze, ponieważ wymagałoby to umieszczenia tam prywatnego klucza recovery.
