import logging

import psycopg2
import psycopg2.extras
import pandas as pd

logger = logging.getLogger(__name__)


class PostgreSQLConnection:
    # Valores del Postgres local; en AWS main.py exige las variables de entorno (falso positivo B107)
    def __init__(  # nosec B107
            self,
            host: str = "localhost",
            database: str = "news_dw",
            user: str = "myuser",
            password: str = "admin",
            port: int = 5432,
            sslmode: str = "prefer",
            connect_timeout: int = 10
    ):
        self.host = host
        self.database = database
        self.user = user
        self.password = password
        self.port = port
        # "prefer" usa SSL si el servidor lo ofrece; en RDS se usa "require"
        self.sslmode = sslmode
        self.connect_timeout = connect_timeout
        self.connection = None

    def connect(self):
        """
        Abre la conexión a PostgreSQL. Si falla, se relanza el error para que la API no arranque sin datos.
        """
        try:
            self.connection = psycopg2.connect(
                host=self.host,
                port=self.port,
                database=self.database,
                user=self.user,
                password=self.password,
                sslmode=self.sslmode,
                connect_timeout=self.connect_timeout
            )
            # Sin autocommit cada SELECT dejaría una transacción abierta en el servidor;
            # las escrituras del módulo de cuentas son sentencias sueltas y atómicas
            self.connection.autocommit = True
            print("Conexión exitosa a la base de datos.")
        except Exception as e:
            print(f"Error al conectar a la base de datos: {e}")
            raise

    def close(self):
        """
        Cierra la conexión a la base de datos si está abierta.
        """
        if self.connection:
            self.connection.close()
            self.connection = None
            print("Conexión cerrada.")


    def query_to_dataframe(self, query: str, params=None) -> pd.DataFrame:
        """
        Ejecuta una consulta SQL y devuelve el resultado como un DataFrame de pandas.
        params se pasa al driver para consultas parametrizadas (%s), sin concatenar valores en el SQL.
        Si la conexión se cerró (reinicio de RDS, timeout de red) se reconecta y se reintenta una vez.
        """
        if not self.connection:
            raise Exception("No hay conexión a la base de datos.")

        if self.connection.closed:
            self.connect()

        try:
            return pd.read_sql(query, self.connection, params=params)
        except (psycopg2.OperationalError, psycopg2.InterfaceError, pd.errors.DatabaseError) as e:
            # pandas envuelve el error del driver en DatabaseError; solo se reintenta si fue la conexión
            cause = e.__cause__ if isinstance(e, pd.errors.DatabaseError) else e
            if not isinstance(cause, (psycopg2.OperationalError, psycopg2.InterfaceError)):
                raise
            logger.warning(f"Conexión a PostgreSQL perdida ({cause}); reconectando")
            self.close()
            self.connect()
            return pd.read_sql(query, self.connection, params=params)

    def execute(self, query: str, params=None, fetch: str = None):
        """
        Ejecuta una sentencia (INSERT/UPDATE/DDL) con autocommit: cada sentencia es atómica.
        fetch: None (nada), "one" (una fila como dict o None) o "all" (lista de dicts).
        Se reconecta y reintenta una vez solo si la conexión se perdió antes de ejecutar.
        """
        if not self.connection:
            raise Exception("No hay conexión a la base de datos.")

        if self.connection.closed:
            self.connect()

        try:
            return self._run(query, params, fetch)
        except (psycopg2.OperationalError, psycopg2.InterfaceError) as e:
            if not self.connection.closed:
                raise
            logger.warning(f"Conexión a PostgreSQL perdida ({e}); reconectando")
            self.close()
            self.connect()
            return self._run(query, params, fetch)

    def _run(self, query, params, fetch):
        with self.connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(query, params)
            if fetch == "one":
                row = cur.fetchone()
                return dict(row) if row else None
            if fetch == "all":
                return [dict(r) for r in cur.fetchall()]
            return cur.rowcount
