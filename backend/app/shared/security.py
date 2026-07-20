"""Security helpers shell (session/CSRF/BYOK encryption land in S1)."""

from cryptography.fernet import Fernet


def generate_fernet_key() -> str:
    """Generate a new Fernet key string for local development."""
    return Fernet.generate_key().decode("ascii")
