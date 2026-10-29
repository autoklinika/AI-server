#!/srv/ai-data/magazyn-v1/runtime/py314/bin/python
"""Repair ONLY the missing certificate of the second YubiKey slot 0x82.

The ECC P-256 private key already exists. No reset, no key generation,
no PIN/PUK changes and no --force. Secrets are entered only via terminal.
"""
from pathlib import Path
import os
import re
import subprocess
import sys
import tempfile

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

ROOT=Path("/srv/ai-data/magazyn-v1")
SPARE=ROOT/"private/yubikey-spare"
FIRST=Path("/srv/ai-data/platform/recovery/stage-k/age-recipients.txt")
PLUGIN="/srv/ai-data/tools/age/usr/bin/age-plugin-yubikey"

def read(*args):
    result=subprocess.run(args,capture_output=True,text=True,timeout=20)
    if result.returncode:
        raise RuntimeError("Unable to inspect YubiKey: "+args[0]+" "+args[1])
    return result.stdout

def stop(reason):
    print("SECOND_YUBIKEY_CERT_REPAIR_BLOCKED:",reason,flush=True)
    raise SystemExit(2)

def exclusive(path,content):
    fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,"wb") as stream:
        stream.write(content)

def verify_prereqs():
    if os.geteuid()==0:
        stop("Run without sudo")
    if not SPARE.is_dir() or SPARE.stat().st_mode & 0o777 != 0o700:
        stop("Private spare directory missing or permissions wrong")
    if any((SPARE/p).exists() for p in ("recipient.txt","identity.txt")):
        stop("Age identity already exists; do not overwrite")
    info=read("ykman","piv","info")
    if ("Management key algorithm: TDES" not in info
        or "Management key is stored on the YubiKey, protected by PIN." not in info
        or "Slot 82 (RETIRED1):" not in info
        or "Private key type: ECCP256" not in info
        or "Using default PIN" in info
        or "Using default PUK" in info):
        stop("PIV state not as expected")
    retries=re.search(r"PIN tries remaining:\s*(\d+)/(\d+)",info)
    if not retries or int(retries[1])<2:
        stop("Too few PIN retries; do not risk blocking the YubiKey")
    meta=read("ykman","piv","keys","info","82")
    if not all(x in meta for x in ("ECCP256","GENERATED","ONCE","ALWAYS")):
        stop("Key policies changed unexpectedly")
    serials=read("ykman","list","--serials").splitlines()
    if len(serials)!=1 or not serials[0].isdigit():
        stop("Connect exactly one YubiKey")
    primary=next((x.strip() for x in FIRST.read_text().splitlines()
                  if x.strip().startswith("age1yubikey1")),None)
    if not primary:
        stop("Primary recipient missing")
    connected=read(PLUGIN,"--list").splitlines()
    if primary in connected:
        stop("Primary YubiKey connected! Do not modify it.")
    print("SECOND_YUBIKEY_ECCP256_PRESENT_NO_OVERWRITE=PASS")
    print("SECOND_YUBIKEY_PIN_RETRIES",retries[1]+"/"+retries[2])
    return serials[0],primary

def perform(mode):
    if mode not in ("--check","--run"):
        stop("Use --check or --run")
    serial,primary=verify_prereqs()
    with tempfile.TemporaryDirectory(dir="/dev/shm",prefix="yubi-spare-cert-") as folder:
        folder=Path(folder)
        public=folder/"public.pem"
        already=folder/"existing.pem"
        r=subprocess.run(["ykman","piv","certificates","export","82",str(already)],
                         stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=12)
        if r.returncode==0:
            stop("Certificate already exists; do not overwrite it")
        subprocess.run(["ykman","piv","keys","export","82",str(public)],
                       check=True,timeout=15)
        key=serialization.load_pem_public_key(public.read_bytes())
        if not isinstance(key,ec.EllipticCurvePublicKey) or not isinstance(key.curve,ec.SECP256R1):
            stop("Public key is not P-256")
        print("SECOND_YUBIKEY_CERT_MISSING_EXISTING_PUBLIC_KEY_VERIFIED=PASS")
        if mode=="--check":
            print("SECOND_YUBIKEY_CERT_REPAIR_PREFLIGHT=PASS")
            return
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            stop("Local interactive SSH terminal required")
        if read("ykman","list","--serials").strip()!=serial:
            stop("YubiKey has been swapped")
        print("Generating ONLY missing X.509 certificate for existing key 0x82.")
        print("Enter your CURRENT new PIN only in this terminal; touch YubiKey when asked.")
        print("Do not retry a failed PIN or touch operation automatically.")
        command=["ykman","piv","certificates","generate",
                 "--subject","CN=Magazyn-V1-Spare-2026,OU=0.5.1,O=age-plugin-yubikey",
                 "--valid-days","3650","82",str(public)]
        if subprocess.run(command,timeout=120).returncode:
            stop("Certificate signing failed; private key remains unchanged")
        certfile=folder/"cert.pem"
        subprocess.run(["ykman","piv","certificates","export","82",str(certfile)],
                       check=True,timeout=15)
        cert=x509.load_pem_x509_certificate(certfile.read_bytes())
        if cert.public_key().public_numbers()!=key.public_numbers():
            stop("Certificate public key does not match slot 0x82")
        if cert.subject.get_attributes_for_oid(NameOID.ORGANIZATION_NAME)[0].value!="age-plugin-yubikey":
            stop("Certificate organization invalid")
        cert.public_key().verify(cert.signature,cert.tbs_certificate_bytes,
                                 ec.ECDSA(cert.signature_hash_algorithm))
        print("SECOND_YUBIKEY_EXISTING_KEY_CERTIFICATE_VERIFIED=PASS")
        known=read(PLUGIN,"--list").splitlines()
        others=[x for x in known if x.startswith("age1yubikey1")]
        if len(others)!=1 or others[0]==primary:
            stop("Certificate added but age recipient is not recognized; do not overwrite key")
        identity=read(PLUGIN,"--identity","--slot","1")
        lines=[x for x in identity.splitlines() if x.startswith("AGE-PLUGIN-YUBIKEY-")]
        if len(lines)!=1:
            stop("Certificate added but age identity is not recognized")
        exclusive(SPARE/"identity.txt",identity.encode())
        exclusive(SPARE/"recipient.txt",(others[0]+"\n").encode())
        print("SECOND_YUBIKEY_EXISTING_KEY_CERTIFICATE_RECOVERED=PASS")
        print("SECOND_YUBIKEY_INDEPENDENT_PIV_KEY=PASS")
        print("SECOND_YUBIKEY_PUBLIC_RECIPIENT_STORED=PASS")
        print("FIRST_YUBIKEY_AND_PRODUCTION_AES_UNCHANGED=PASS")

if __name__=="__main__":
    try:
        if len(sys.argv)!=2:
            stop("Pass --check or --run")
        perform(sys.argv[1])
    except (OSError,ValueError,RuntimeError,subprocess.SubprocessError) as exc:
        stop(type(exc).__name__)
