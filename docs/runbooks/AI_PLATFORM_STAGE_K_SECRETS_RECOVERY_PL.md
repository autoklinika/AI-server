# AI Platform — Stage K Secrets Recovery Runbook

## Cel

Sekrety Stage K są archiwizowane jako `secrets.tar.gz.age` pod
`AI_Platform/Platform/secrets/<tier>/<backup_id>/`.

Od 2026-09-25 docelowym mechanizmem recovery jest `age-plugin-yubikey` z kluczem
PIV ECC P-256 wygenerowanym wewnątrz YubiKey 5C. AI Server przechowuje wyłącznie
publiczny recipient potrzebny do szyfrowania. Prywatny materiał klucza nie opuszcza
YubiKeya.

Historyczne bundle utworzone przed migracją mogą nadal używać `ssh-ed25519`.
`k3_secrets_verify.py` zachowuje ich kompatybilność i weryfikuje historyczny
zaakceptowany fingerprint.
## Bieżąca polityka YubiKey

Pierwszy klucz recovery:
- YubiKey 5C, PIV `RETIRED1` / slot `0x82`;
- algorytm ECC P-256;
- `PIN policy = once`;
- `Touch policy = never`;
- management key jest losowy i przechowywany na YubiKeyu pod ochroną PIN-u.

Automatyczny backup nie wymaga podłączonego YubiKeya. `age` korzysta tylko z
publicznego recipienta. YubiKey jest wymagany dopiero do odszyfrowania.

Po zakończeniu recovery należy odłączyć YubiKey. Odłączenie kończy sesję PIV i
czyści cache PIN wynikający z polityki `once`.
## Weryfikacja przed decrypt

Na AI Serverze lub recovery host uruchom:

```bash
python3 deploy/stage-k/k3_secrets_verify.py \
  /mnt/AI_Platform/Platform/secrets/<tier>/<backup_id>
```

Wynik musi mieć `"status": "PASS"`. Dla nowych backupów oczekiwany jest
`"recipient_type": "age-plugin-yubikey"` i `manifest_schema_version = 2`.

Nie odszyfrowuj bundle, którego integralność lub recipient policy nie przechodzi
weryfikacji.
## Przygotowanie identity stub na recovery host

Identity stub nie zawiera prywatnego klucza. Można go odtworzyć z podłączonego
YubiKeya:

```bash
age-plugin-yubikey --identity --slot 1 > yubikey-identity.txt
chmod 600 yubikey-identity.txt
```

Publiczny recipient można sprawdzić:

```bash
age-plugin-yubikey --list
```

Do normalnego backupu plik identity nie jest wymagany.
## Decrypt test

Po zweryfikowaniu bundle:

```bash
age -d \
  -i yubikey-identity.txt \
  -o /tmp/stage-k-secrets.tar.gz \
  secrets.tar.gz.age

tar -tzf /tmp/stage-k-secrets.tar.gz
```

Program poprosi o PIN zgodnie z polityką PIV. Fizyczne dotknięcie klucza nie jest
wymagane. Po kontroli usuń plaintext:

```bash
rm -f /tmp/stage-k-secrets.tar.gz
```
## Preferowany restore bez plaintextowego archiwum

Na replacement host preferowany jest streaming decrypt:

```bash
age -d -i yubikey-identity.txt secrets.tar.gz.age | \
  ssh <recovery-host> 'sudo tar -xzf - -C /'
```

Przed restore sprawdź listę plików, docelowe owner/mode i zatrzymaj usługi
korzystające z przywracanych sekretów. Po restore wykonaj health check AI Bridge,
AI Gateway, Hermes oraz dostępu do GlobalNAS.
## Drugi YubiKey 5C

Każdy YubiKey ma własny niezależny klucz PIV. Nie klonujemy prywatnych kluczy.

Po dodaniu drugiego 5C:
1. wygeneruj jego identity w odpowiednim retired slocie;
2. dopisz publiczny recipient do `age-recipients.txt`;
3. dodaj recipient do `ACCEPTED_YUBIKEY_RECIPIENTS` oraz aktywnej polityki w
   `deploy/stage-k/k3_recipients.py`;
4. uruchom testy i wykonaj decrypt tego samego testowego bundle każdym YubiKeyem.

`age` zaszyfruje nowe bundle do obu recipientów. Każdy z dwóch kluczy będzie mógł
samodzielnie wykonać recovery. Stare backupy pozostają weryfikowalne według
recipientów zapisanych w ich własnym `manifest.json`.
## Wymagania hosta AI Server

Runtime Stage K używa:
- `/srv/ai-data/tools/age/usr/bin/age` 1.2.1;
- `/srv/ai-data/tools/age/usr/bin/age-plugin-yubikey` 0.5.1;
- `pcscd` + `libccid` do operacji PIV/recovery.

Na tym hoście wymagane są dodatkowo dwie lokalne reguły:
- `/etc/polkit-1/rules.d/60-pcsc-harrypotter.rules` — dostęp użytkownika `harrypotter` do PC/SC z sesji zdalnej;
- `/etc/udev/rules.d/99-yubikey-pcsc.rules` — urządzenia Yubico smart-card otrzymują grupę `pcscd` i tryb `0660`.

Brak reguły udev objawia się w `pcscd` jako `LIBUSB_ERROR_ACCESS`. Nie należy omijać tego przez globalne `MODE=0666` ani uruchamianie `pcscd` jako root.
