import psycopg2
import pandas as pd

class PostgreSQLConnection:
    def __init__(self, host: str, database: str, user: str, password: str, port: int = 5432):
        self.host = host
        self.database = database
        self.user = user
        self.password = password
        self.port = port
        self.connection = None

    def connect(self):
        try:
            self.connection = psycopg2.connect(
                host=self.host,
                database=self.database,
                user=self.user,
                password=self.password
            )
            print("Conexión exitosa a la base de datos.")
        except Exception as e:
            print(f"Error al conectar a la base de datos: {e}")

    def close(self):
        """
        Cierra la conexión a la base de datos si está abierta.
        """
        if self.connection:
            self.connection.close()
            print("Conexión cerrada.")


    def query_to_dataframe(self, query: str) -> pd.DataFrame:
        """
        Ejecuta una consulta SQL y devuelve el resultado como un DataFrame de pandas.
        """
        if not self.connection:
            raise Exception("No hay conexión a la base de datos.")
        
        
        return pd.read_sql(query, self.connection)