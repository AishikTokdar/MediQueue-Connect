import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "server"))

from crypto_utils import (
    crypto_available,
    generate_ecdh_keypair,
    derive_ecdh_shared_key,
    encrypt_message,
    decrypt_message,
)


def test_crypto_available_flag():
    assert crypto_available() is True


def test_ecdh_x25519_key_exchange_agreement():
    # Alice generates ephemeral keypair
    alice_priv, alice_pub_b64 = generate_ecdh_keypair()
    assert isinstance(alice_pub_b64, str)
    assert len(alice_pub_b64) > 20

    # Bob generates ephemeral keypair
    bob_priv, bob_pub_b64 = generate_ecdh_keypair()
    assert isinstance(bob_pub_b64, str)

    # Both derive shared symmetric key using peer's public key
    alice_derived_key = derive_ecdh_shared_key(alice_priv, bob_pub_b64)
    bob_derived_key = derive_ecdh_shared_key(bob_priv, alice_pub_b64)

    # Keys must match exactly (Perfect Forward Secrecy)
    assert alice_derived_key == bob_derived_key
    assert len(alice_derived_key) == 44  # Standard base64-encoded 32-byte key


def test_message_encryption_and_decryption_roundtrip():
    _, pub_b64 = generate_ecdh_keypair()
    priv, _ = generate_ecdh_keypair()
    shared_key = derive_ecdh_shared_key(priv, pub_b64)

    original_message = "Patient blood pressure: 120/80 mmHg. Pulse: 72 bpm."
    ciphertext = encrypt_message(original_message, shared_key)
    assert ciphertext != original_message

    decrypted = decrypt_message(ciphertext, shared_key)
    assert decrypted == original_message


def test_tampered_ciphertext_detection():
    priv, pub_b64 = generate_ecdh_keypair()
    peer_priv, peer_pub_b64 = generate_ecdh_keypair()
    key = derive_ecdh_shared_key(priv, peer_pub_b64)

    original_message = "Clinical diagnosis: Normal sinus rhythm"
    ciphertext = encrypt_message(original_message, key)

    # Tamper with the ciphertext
    tampered = ciphertext[:-4] + "XXXX"
    result = decrypt_message(tampered, key)
    assert result == "[DECRYPTION FAILED]"


def test_doctor_peer_invite_ecdh_negotiation():
    # Doctor A invites Doctor B: Doctor A generates ephemeral keypair
    doc_a_priv, doc_a_pub_b64 = generate_ecdh_keypair()

    # Doctor B receives invite and generates its ephemeral keypair
    doc_b_priv, doc_b_pub_b64 = generate_ecdh_keypair()

    # Doctor B derives shared consultation key
    doc_b_key = derive_ecdh_shared_key(doc_b_priv, doc_a_pub_b64)

    # Doctor A receives Doctor B's public key and derives identical consultation key
    doc_a_key = derive_ecdh_shared_key(doc_a_priv, doc_b_pub_b64)

    assert doc_a_key == doc_b_key
    assert len(doc_a_key) == 44

    # Verify bidirectional consultation exchange between doctors
    doc_a_note = "Dr. B, please review ECG telemetry for this patient."
    encrypted_note = encrypt_message(doc_a_note, doc_a_key)
    decrypted_note = decrypt_message(encrypted_note, doc_b_key)
    assert decrypted_note == doc_a_note

