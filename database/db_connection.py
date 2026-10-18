import psycopg2
import pandas as pd

class PostgreSQLConnection:
    def __init__(
            self,
            host: str = "localhost",
            database: str = "news_dw",
            user: str = "myuser",
            password: str = "admin",
            port: int = 5432
    ):
        self.host = host
        self.database = database
        self.user = user
        self.password = password
        self.port = port
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
                password=self.password
            )
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
        """
        if not self.connection:
            raise Exception("No hay conexión a la base de datos.")


        return pd.read_sql(query, self.connection, params=params)
