import logging

import psycopg2
import pandas as pd

logger = logging.getLogger(__name__)


class PostgreSQLConnection:
    def __init__(
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
            # Solo se hacen lecturas: sin autocommit cada SELECT dejaría una transacción abierta en el servidor
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
