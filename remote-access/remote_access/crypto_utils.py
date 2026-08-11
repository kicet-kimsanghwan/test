"""Self-signed TLS certificate management with TOFU (trust-on-first-use)
fingerprint pinning, so the video/control channel is encrypted and a client
can detect if a host's certificate ever changes unexpectedly (e.g. MITM)."""
import datetime
import hashlib
import json
import os
import ssl
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

CONFIG_DIR = Path.home() / ".remote_access"
CERT_PATH = CONFIG_DIR / "host_cert.pem"
KEY_PATH = CONFIG_DIR / "host_key.pem"
TRUST_STORE_PATH = CONFIG_DIR / "trusted_hosts.json"


def ensure_host_certificate():
    """Return (cert_path, key_path), generating a self-signed cert on first run."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if CERT_PATH.exists() and KEY_PATH.exists():
        return str(CERT_PATH), str(KEY_PATH)

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "remote-access-host")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.utcnow() - datetime.timedelta(days=1))
        .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=3650))
        .sign(key, hashes.SHA256())
    )

    KEY_PATH.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    os.chmod(KEY_PATH, 0o600)
    CERT_PATH.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return str(CERT_PATH), str(KEY_PATH)


def build_server_context():
    cert_path, key_path = ensure_host_certificate()
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(cert_path, key_path)
    return ctx


def build_client_context():
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE  # self-signed cert; verified via TOFU pinning below instead
    return ctx


def fingerprint_of_der(der_bytes):
    digest = hashlib.sha256(der_bytes).hexdigest()
    return ":".join(digest[i : i + 2] for i in range(0, len(digest), 2))


def fingerprint_of_pem_file(path):
    cert = x509.load_pem_x509_certificate(Path(path).read_bytes())
    return fingerprint_of_der(cert.public_bytes(serialization.Encoding.DER))


def _load_trust_store():
    if TRUST_STORE_PATH.exists():
        return json.loads(TRUST_STORE_PATH.read_text())
    return {}


def _save_trust_store(store):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    TRUST_STORE_PATH.write_text(json.dumps(store, indent=2))


def verify_and_pin(host, port, fingerprint, expected_fingerprint=None):
    """TOFU check: trust a host's cert on first connect, then require it to
    match on every later connect. Returns None on success, or an error
    message describing why the connection should be aborted."""
    if expected_fingerprint:
        expected_fingerprint = expected_fingerprint.lower()
        if fingerprint.lower() != expected_fingerprint:
            return (
                "Certificate fingerprint mismatch!\n"
                f"  expected: {expected_fingerprint}\n"
                f"  got:      {fingerprint}"
            )
        return None

    key = f"{host}:{port}"
    store = _load_trust_store()
    known = store.get(key)
    if known is None:
        store[key] = fingerprint
        _save_trust_store(store)
        print(f"[TOFU] Trusting new host {key} with fingerprint {fingerprint}")
        print("        Verify this out-of-band with the host owner if possible.")
        return None
    if known.lower() != fingerprint.lower():
        return (
            f"WARNING: certificate fingerprint for {key} changed!\n"
            f"  previously trusted: {known}\n"
            f"  now presented:      {fingerprint}\n"
            "This could mean the host was reinstalled, or a man-in-the-middle attack.\n"
            f"Refusing to connect. Delete the entry in {TRUST_STORE_PATH} if this is expected."
        )
    return None
