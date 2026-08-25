import base64
import hashlib
import os
import ssl
import socket
import sys

try:
    from cryptography.fernet import Fernet, InvalidToken
    _CRYPTO_AVAILABLE = True
except ImportError:
    _CRYPTO_AVAILABLE = False

APP_PASSPHRASE = b"blue-scrubs-and-cold-coffee-2026"


def _derive_key(passphrase: bytes) -> bytes:
    digest = hashlib.sha256(passphrase).digest()
    return base64.urlsafe_b64encode(digest)


def generate_session_key() -> bytes:
    if not _CRYPTO_AVAILABLE:
        raise RuntimeError("cryptography package is not installed. Run: pip install cryptography")
    return Fernet.generate_key()


def encrypt_session_key(session_key: bytes, passphrase: bytes = APP_PASSPHRASE) -> str:
    if not _CRYPTO_AVAILABLE:
        raise RuntimeError("cryptography package not installed")
    return Fernet(_derive_key(passphrase)).encrypt(session_key).decode()


def decrypt_session_key(encrypted_key: str, passphrase: bytes = APP_PASSPHRASE) -> bytes:
    if not _CRYPTO_AVAILABLE:
        raise RuntimeError("cryptography package not installed")
    return Fernet(_derive_key(passphrase)).decrypt(encrypted_key.encode())


def encrypt_message(plaintext: str, session_key: bytes) -> str:
    if not _CRYPTO_AVAILABLE:
        return plaintext
    return Fernet(session_key).encrypt(plaintext.encode()).decode()


def decrypt_message(ciphertext: str, session_key: bytes) -> str:
    if not _CRYPTO_AVAILABLE:
        return ciphertext
    try:
        return Fernet(session_key).decrypt(ciphertext.encode()).decode()
    except InvalidToken:
        return "[DECRYPTION FAILED]"


def crypto_available() -> bool:
    return _CRYPTO_AVAILABLE


def ensure_tls_certificates() -> tuple[str, str]:
    """Generates self-signed TLS certificates for local TCP server encryption if not already present."""
    cert_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "certs")
    os.makedirs(cert_dir, exist_ok=True)
    cert_path = os.path.join(cert_dir, "server.crt")
    key_path = os.path.join(cert_dir, "server.key")

    if not os.path.exists(cert_path) or not os.path.exists(key_path):
        import ipaddress
        import datetime
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = issuer = x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "MediQueue Connect"),
        ])
        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.datetime.now(datetime.timezone.utc))
            .not_valid_after(datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=3650))
            .add_extension(
                x509.SubjectAlternativeName([
                    x509.DNSName("localhost"),
                    x509.IPAddress(ipaddress.ip_address("127.0.0.1"))
                ]),
                critical=False,
            )
            .sign(key, hashes.SHA256())
        )

        with open(key_path, "wb") as f:
            f.write(key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption(),
            ))

        with open(cert_path, "wb") as f:
            f.write(cert.public_bytes(serialization.Encoding.PEM))

    return cert_path, key_path


def get_server_ssl_context() -> ssl.SSLContext:
    """Returns an SSLContext configured for TLS server mode."""
    cert_path, key_path = ensure_tls_certificates()
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certfile=cert_path, keyfile=key_path)
    return context


def get_client_ssl_context() -> ssl.SSLContext:
    """Returns an SSLContext configured for TLS client mode (accepting self-signed dev certificates)."""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


def wrap_client_socket(sock: socket.socket, server_hostname: str = "127.0.0.1") -> ssl.SSLSocket:
    """Wraps an established TCP socket with TLS encryption."""
    ctx = get_client_ssl_context()
    return ctx.wrap_socket(sock, server_hostname=server_hostname)
