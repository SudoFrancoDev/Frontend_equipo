from pathlib import Path

# El DDL vive en POSTGRES_BD/ junto al resto del esquema; el Dockerfile lo copia a la imagen
SCHEMA_FILE = Path(__file__).resolve().parent.parent / "POSTGRES_BD" / "create_auth_tables.sql"


class UserRepository:
    """
    Acceso a app.app_user. Las reglas que dependen del tiempo se evalúan con now() de PostgreSQL
    y en una sola sentencia, para que dos peticiones simultáneas no se salten el bloqueo ni la
    sesión única.
    """

    def __init__(self, db_connection):
        self.db = db_connection

    def ensure_schema(self):
        """Crea el esquema app y la tabla si no existen (el script es idempotente)."""
        self.db.execute(SCHEMA_FILE.read_text(encoding="utf-8"))

    # ── Registro y búsqueda ───────────────────
    def create(self, email_hash: str, email_enc: str, name_enc: str, password_hash: str):
        """Devuelve el user_id, o None si el correo ya estaba registrado."""
        row = self.db.execute(
            """
            INSERT INTO app.app_user (email_hash, email_enc, name_enc, password_hash)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (email_hash) DO NOTHING
            RETURNING user_id;""",
            (email_hash, email_enc, name_enc, password_hash), fetch="one")
        return row["user_id"] if row else None

    def get_by_email_hash(self, email_hash: str):
        return self.db.execute(
            """
            SELECT user_id, email_enc, name_enc, password_hash, failed_attempts, locked_until,
                   locked_until IS NOT NULL AND locked_until > now() AS is_locked,
                   GREATEST(0, CEIL(EXTRACT(EPOCH FROM locked_until - now()) / 60))::int AS locked_minutes
            FROM app.app_user WHERE email_hash = %s;""",
            (email_hash,), fetch="one")

    # ── Intentos fallidos y bloqueo ───────────
    def register_failed_attempt(self, user_id: int, max_attempts: int, lock_seconds: int):
        """
        Suma un intento fallido; al llegar a max_attempts bloquea la cuenta lock_seconds y
        reinicia el contador. Devuelve failed_attempts y si quedó bloqueada.
        """
        return self.db.execute(
            """
            UPDATE app.app_user SET
                locked_until    = CASE WHEN failed_attempts + 1 >= %(max)s
                                       THEN now() + make_interval(secs => %(lock)s) ELSE locked_until END,
                failed_attempts = CASE WHEN failed_attempts + 1 >= %(max)s THEN 0 ELSE failed_attempts + 1 END,
                updated_at      = now()
            WHERE user_id = %(id)s
            RETURNING failed_attempts, locked_until IS NOT NULL AND locked_until > now() AS is_locked;""",
            {"id": user_id, "max": max_attempts, "lock": lock_seconds}, fetch="one")

    # ── Sesión única ──────────────────────────
    def start_session(self, user_id: int, session_hash: str, idle_seconds: int, max_seconds: int,
                      force: bool) -> bool:
        """
        Abre la sesión si no hay otra activa (o si force=True, cerrando la anterior).
        Una sesión está activa si tuvo actividad hace menos de idle_seconds y no superó max_seconds.
        Devuelve False si había otra sesión activa y no se forzó.
        """
        row = self.db.execute(
            """
            UPDATE app.app_user SET
                session_token_hash    = %(hash)s,
                session_created_at    = now(),
                session_last_activity = now(),
                failed_attempts       = 0,
                locked_until          = NULL,
                last_login_at         = now(),
                updated_at            = now()
            WHERE user_id = %(id)s
              AND (%(force)s
                   OR session_token_hash IS NULL
                   OR session_last_activity < now() - make_interval(secs => %(idle)s)
                   OR session_created_at    < now() - make_interval(secs => %(max)s))
            RETURNING user_id;""",
            {"id": user_id, "hash": session_hash, "idle": idle_seconds, "max": max_seconds, "force": force},
            fetch="one")
        return row is not None

    def touch_session(self, session_hash: str, idle_seconds: int, max_seconds: int):
        """
        Valida el token y renueva su última actividad (expiración deslizante).
        Devuelve los datos del usuario, o None si el token no existe o ya expiró.
        """
        return self.db.execute(
            """
            UPDATE app.app_user SET session_last_activity = now()
            WHERE session_token_hash = %(hash)s
              AND session_last_activity >= now() - make_interval(secs => %(idle)s)
              AND session_created_at    >= now() - make_interval(secs => %(max)s)
            RETURNING user_id, email_enc, name_enc;""",
            {"hash": session_hash, "idle": idle_seconds, "max": max_seconds}, fetch="one")

    def end_session(self, session_hash: str) -> bool:
        """Cierra la sesión del token (también se usa para limpiar un token expirado)."""
        return self.db.execute(
            """
            UPDATE app.app_user SET session_token_hash = NULL, session_created_at = NULL,
                                    session_last_activity = NULL, updated_at = now()
            WHERE session_token_hash = %s;""",
            (session_hash,)) > 0

    # ── Recuperación de contraseña ────────────
    def set_reset_token(self, user_id: int, reset_hash: str, ttl_seconds: int, cooldown_seconds: int) -> bool:
        """Guarda un token nuevo de recuperación; False si se pidió otro hace menos de cooldown_seconds."""
        row = self.db.execute(
            """
            UPDATE app.app_user SET
                reset_token_hash   = %(hash)s,
                reset_expires_at   = now() + make_interval(secs => %(ttl)s),
                reset_requested_at = now(),
                updated_at         = now()
            WHERE user_id = %(id)s
              AND (reset_requested_at IS NULL
                   OR reset_requested_at < now() - make_interval(secs => %(cooldown)s))
            RETURNING user_id;""",
            {"id": user_id, "hash": reset_hash, "ttl": ttl_seconds, "cooldown": cooldown_seconds}, fetch="one")
        return row is not None

    def reset_password(self, reset_hash: str, password_hash: str) -> bool:
        """
        Cambia la contraseña si el token es válido y no expiró. El token es de un solo uso;
        además desbloquea la cuenta y cierra la sesión abierta.
        """
        row = self.db.execute(
            """
            UPDATE app.app_user SET
                password_hash         = %(pw)s,
                reset_token_hash      = NULL,
                reset_expires_at      = NULL,
                failed_attempts       = 0,
                locked_until          = NULL,
                session_token_hash    = NULL,
                session_created_at    = NULL,
                session_last_activity = NULL,
                updated_at            = now()
            WHERE reset_token_hash = %(hash)s AND reset_expires_at > now()
            RETURNING user_id;""",
            {"hash": reset_hash, "pw": password_hash}, fetch="one")
        return row is not None
