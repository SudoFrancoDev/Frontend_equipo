"""
Módulo opcional de cuentas: registro, inicio/cierre de sesión, sesión actual y recuperación
de contraseña. Buscar y navegar artículos no requiere sesión.

Reglas:
- Contraseña de mínimo 8 caracteres con números, mayúsculas y caracteres especiales.
- Un correo solo se puede registrar una vez.
- 5 contraseñas incorrectas seguidas bloquean la cuenta temporalmente.
- Una sola sesión activa por cuenta: si hay otra abierta en otro navegador se rechaza el inicio
  de sesión, salvo que el usuario confirme cerrar la otra (force=true).
- El token expira tras AUTH_TOKEN_IDLE_MINUTES sin peticiones (expiración deslizante) y, en todo
  caso, a las AUTH_SESSION_MAX_HOURS. El frontend cierra además la sesión tras
  AUTH_SESSION_IDLE_MINUTES sin actividad del usuario en la aplicación.
"""
import logging
import os

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from auth import security
from auth.mailer import ResetMailer
from repository.user_repository import UserRepository

logger = logging.getLogger(__name__)

APP_MODE = os.getenv("APP_MODE", "local")

# Clave de desarrollo: solo se acepta en local. En AWS se define AUTH_SECRET_KEY (Secrets Manager)
DEV_SECRET_KEY = "datara-local-dev-key-no-usar-en-produccion-0000"


def _int_env(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


TOKEN_IDLE_SECONDS   = _int_env("AUTH_TOKEN_IDLE_MINUTES", 30) * 60     # inactividad del token (API)
SESSION_IDLE_SECONDS = _int_env("AUTH_SESSION_IDLE_MINUTES", 15) * 60   # inactividad en la aplicación
SESSION_MAX_SECONDS  = _int_env("AUTH_SESSION_MAX_HOURS", 12) * 3600    # duración máxima de una sesión
MAX_FAILED_ATTEMPTS  = _int_env("AUTH_MAX_FAILED_ATTEMPTS", 5)
LOCKOUT_SECONDS      = _int_env("AUTH_LOCKOUT_MINUTES", 15) * 60
RESET_TTL_SECONDS    = _int_env("AUTH_RESET_TOKEN_MINUTES", 30) * 60
RESET_COOLDOWN_SECONDS = 60                                             # entre dos correos de recuperación
# Página del frontend que recibe el enlace de recuperación (el token va en el fragmento #reset=)
RESET_URL = os.getenv("AUTH_RESET_URL", "http://localhost:5500/login.html")

GENERIC_LOGIN_ERROR = "Correo o contraseña incorrectos"

router = APIRouter(prefix="/auth", tags=["auth"])
bearer = HTTPBearer(auto_error=False)

users: UserRepository = None
crypto: security.Crypto = None
mailer: ResetMailer = None


def setup(db):
    """Se llama al arrancar la API: crea la tabla si no existe y prepara cifrado y correo."""
    global users, crypto, mailer

    secret = os.getenv("AUTH_SECRET_KEY", "").strip()
    if not secret:
        if APP_MODE != "local":
            raise RuntimeError("Falta la variable de entorno AUTH_SECRET_KEY")
        logger.warning("AUTH_SECRET_KEY no definido: se usa la clave de desarrollo (solo local)")
        secret = DEV_SECRET_KEY
    if SESSION_IDLE_SECONDS > TOKEN_IDLE_SECONDS:
        logger.warning("AUTH_SESSION_IDLE_MINUTES es mayor que AUTH_TOKEN_IDLE_MINUTES: "
                       "el token expirará antes que la sesión de la aplicación")

    crypto = security.Crypto(secret)
    users = UserRepository(db)
    users.ensure_schema()
    mailer = ResetMailer(os.getenv("AUTH_MAIL_SENDER", "").strip(), os.getenv("AWS_REGION", "us-east-1"), APP_MODE)
    logger.info("Módulo de cuentas listo (tabla app.app_user)")


# ─────────────────────────────────────────────
# Schemas
# ─────────────────────────────────────────────
class RegisterRequest(BaseModel):
    name: str
    email: str
    password: str


class LoginRequest(BaseModel):
    email: str
    password: str
    force: bool = False   # cerrar la sesión abierta en otro navegador


class ForgotPasswordRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    token: str
    password: str


# ─────────────────────────────────────────────
# Utilidades
# ─────────────────────────────────────────────
def _require_ready():
    if users is None:
        raise HTTPException(status_code=503, detail="El módulo de cuentas no está disponible")


def _check_password_policy(password: str):
    errors = security.password_errors(password)
    if errors:
        raise HTTPException(status_code=422, detail="La contraseña debe tener " + ", ".join(errors) + ".")


def _session_payload(row) -> dict:
    return {
        "user": {"name": crypto.decrypt(row["name_enc"]), "email": crypto.decrypt(row["email_enc"])},
        "token_idle_seconds": TOKEN_IDLE_SECONDS,
        "session_idle_seconds": SESSION_IDLE_SECONDS,
    }


def current_session(credentials: HTTPAuthorizationCredentials = Depends(bearer)):
    """
    Dependencia de los endpoints con sesión: valida el token y renueva su actividad.
    Distingue el token expirado por inactividad del que se cerró en otro navegador.
    """
    _require_ready()
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Inicia sesión para continuar")

    session_hash = security.token_hash(credentials.credentials)
    row = users.touch_session(session_hash, TOKEN_IDLE_SECONDS, SESSION_MAX_SECONDS)
    if row is None:
        # Si el token seguía guardado es que expiró: se limpia para liberar la sesión
        if users.end_session(session_hash):
            raise HTTPException(status_code=401, detail="Tu sesión expiró por inactividad. Inicia sesión de nuevo.")
        raise HTTPException(status_code=401,
                            detail="Tu sesión se cerró: se inició sesión en otro navegador o ya no es válida.")
    row["session_hash"] = session_hash
    return row


# ─────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────
@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(req: RegisterRequest):
    """Crea una cuenta. El correo y el nombre se guardan cifrados y la contraseña con Argon2id."""
    _require_ready()
    name = " ".join(req.name.split())
    if not 2 <= len(name) <= 80:
        raise HTTPException(status_code=422, detail="El nombre debe tener entre 2 y 80 caracteres.")
    if not security.is_valid_email(req.email):
        raise HTTPException(status_code=422, detail="El correo no es válido.")
    _check_password_policy(req.password)

    email = security.normalize_email(req.email)
    user_id = users.create(
        crypto.email_hash(email), crypto.encrypt(email), crypto.encrypt(name), security.hash_password(req.password))
    if user_id is None:
        raise HTTPException(status_code=409, detail="Ya existe una cuenta registrada con este correo.")
    return {"message": "Cuenta creada. Ya puedes iniciar sesión."}


@router.post("/login")
def login(req: LoginRequest):
    """
    Inicia sesión y devuelve el token. Respuestas:
    401 credenciales incorrectas · 423 cuenta bloqueada · 409 sesión activa en otro navegador.
    """
    _require_ready()
    row = users.get_by_email_hash(crypto.email_hash(req.email)) if security.is_valid_email(req.email) else None
    if row is None:
        security.burn_password_check(req.password)
        raise HTTPException(status_code=401, detail=GENERIC_LOGIN_ERROR)

    if row["is_locked"]:
        raise HTTPException(status_code=423, detail=(
            "Tu cuenta está bloqueada temporalmente por varios intentos fallidos. "
            f"Intenta de nuevo en {max(1, row['locked_minutes'])} min o restablece tu contraseña."))

    if not security.verify_password(row["password_hash"], req.password):
        attempt = users.register_failed_attempt(row["user_id"], MAX_FAILED_ATTEMPTS, LOCKOUT_SECONDS)
        if attempt["is_locked"]:
            raise HTTPException(status_code=423, detail=(
                f"Ingresaste {MAX_FAILED_ATTEMPTS} veces una contraseña incorrecta. Tu cuenta quedó "
                f"bloqueada durante {LOCKOUT_SECONDS // 60} min."))
        left = MAX_FAILED_ATTEMPTS - attempt["failed_attempts"]
        raise HTTPException(status_code=401, detail=(
            f"{GENERIC_LOGIN_ERROR}. Te queda{'n' if left > 1 else ''} {left} intento{'s' if left > 1 else ''} "
            "antes del bloqueo temporal."))

    token = security.new_token()
    if not users.start_session(row["user_id"], security.token_hash(token),
                               TOKEN_IDLE_SECONDS, SESSION_MAX_SECONDS, req.force):
        raise HTTPException(status_code=409, detail=(
            "Ya hay una sesión activa con esta cuenta en otro navegador. "
            "Ciérrala allí o confirma para cerrarla e ingresar aquí."))

    return {"token": token, **_session_payload(row)}


@router.get("/me")
def me(session=Depends(current_session)):
    """Datos de la sesión actual. Cada llamada renueva la actividad del token."""
    return _session_payload(session)


@router.post("/logout")
def logout(session=Depends(current_session)):
    users.end_session(session["session_hash"])
    return {"message": "Sesión cerrada"}


@router.post("/forgot-password")
def forgot_password(req: ForgotPasswordRequest):
    """
    Envía al correo un enlace para restablecer la contraseña.
    La respuesta es la misma exista o no la cuenta, para no revelar qué correos están registrados.
    """
    _require_ready()
    message = {"message": "Si el correo está registrado, te enviamos un enlace para restablecer la contraseña."}
    if not security.is_valid_email(req.email):
        raise HTTPException(status_code=422, detail="El correo no es válido.")

    row = users.get_by_email_hash(crypto.email_hash(req.email))
    if row is None:
        return message

    token = security.new_token()
    if users.set_reset_token(row["user_id"], security.token_hash(token), RESET_TTL_SECONDS, RESET_COOLDOWN_SECONDS):
        mailer.send_reset_link(crypto.decrypt(row["email_enc"]), crypto.decrypt(row["name_enc"]),
                               f"{RESET_URL}#reset={token}", RESET_TTL_SECONDS // 60)
    return message


@router.post("/reset-password")
def reset_password(req: ResetPasswordRequest):
    """Cambia la contraseña con el token del correo (un solo uso); desbloquea la cuenta y cierra la sesión."""
    _require_ready()
    _check_password_policy(req.password)
    if not users.reset_password(security.token_hash(req.token), security.hash_password(req.password)):
        raise HTTPException(status_code=400, detail="El enlace no es válido o ya expiró. Solicita uno nuevo.")
    return {"message": "Contraseña actualizada. Ya puedes iniciar sesión."}
