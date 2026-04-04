import base64
import hashlib

try:
    from cryptography.fernet import Fernet, InvalidToken
    _CRYPTO_AVAILABLE = True
except ImportError:
    _CRYPTO_AVAILABLE = False

APP_PASSPHRASE = b"HealthcareCN2024SecretPassphrase!"


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
