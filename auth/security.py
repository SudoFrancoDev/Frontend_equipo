"""
Utilidades criptográficas del módulo de cuentas.

- Contraseñas: Argon2id (hash lento con sal, no reversible).
- Correo y nombre: cifrados con Fernet (AES-128-CBC + HMAC-SHA256); se pueden descifrar
  para mostrar el perfil o enviar el correo de recuperación.
- email_hash: HMAC-SHA256 del correo normalizado, para buscarlo y exigir que sea único
  sin guardarlo en claro.
- Tokens de sesión y de recuperación: aleatorios; en la BD solo se guarda su SHA-256.

Las dos claves (cifrado y HMAC) se derivan con HKDF de AUTH_SECRET_KEY: cambiarla deja
ilegibles los datos ya guardados.
"""
import base64
import hashlib
import hmac
import re
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 128
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

_hasher = PasswordHasher()   # Argon2id con los parámetros recomendados por la librería
# Hash de una contraseña aleatoria: se verifica contra él cuando el correo no existe,
# para que la respuesta tarde lo mismo y no revele qué correos están registrados
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))


def _derive(secret: str, purpose: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=purpose).derive(secret.encode())


class Crypto:
    def __init__(self, secret_key: str):
        if len(secret_key) < 32:
            raise ValueError("AUTH_SECRET_KEY debe tener al menos 32 caracteres")
        self._fernet = Fernet(base64.urlsafe_b64encode(_derive(secret_key, b"datara-auth-encryption")))
        self._hmac_key = _derive(secret_key, b"datara-auth-email-index")

    def encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode()).decode()

    def decrypt(self, value: str) -> str:
        try:
            return self._fernet.decrypt(value.encode()).decode()
        except InvalidToken as e:
            raise ValueError("No se pudo descifrar el dato (¿cambió AUTH_SECRET_KEY?)") from e

    def email_hash(self, email: str) -> str:
        return hmac.new(self._hmac_key, normalize_email(email).encode(), hashlib.sha256).hexdigest()


# ─────────────────────────────────────────────
# Correo y contraseña
# ─────────────────────────────────────────────
def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def is_valid_email(email: str) -> bool:
    email = normalize_email(email)
    return len(email) <= 254 and bool(EMAIL_RE.match(email))


def password_errors(password: str) -> list:
    """
    Política: mínimo 8 caracteres combinando números, mayúsculas y caracteres especiales.
    Devuelve la lista de requisitos que no se cumplen (vacía = válida).
    """
    password = password or ""
    errors = []
    if len(password) < PASSWORD_MIN_LENGTH:
        errors.append(f"al menos {PASSWORD_MIN_LENGTH} caracteres")
    if len(password) > PASSWORD_MAX_LENGTH:
        errors.append(f"como máximo {PASSWORD_MAX_LENGTH} caracteres")
    if not re.search(r"[0-9]", password):
        errors.append("un número")
    if not re.search(r"[A-ZÁÉÍÓÚÑÜ]", password):
        errors.append("una letra mayúscula")
    if not re.search(r"[^A-Za-z0-9ÁÉÍÓÚÑÜáéíóúñü\s]", password):
        errors.append("un carácter especial (por ejemplo ! @ # $ % & *)")
    return errors


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def burn_password_check(password: str):
    """Mismo costo que verify_password cuando no hay usuario (evita distinguir por tiempo)."""
    verify_password(_DUMMY_HASH, password)


# ─────────────────────────────────────────────
# Tokens
# ─────────────────────────────────────────────
def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256((token or "").encode()).hexdigest()
