import json
import re

import boto3
from botocore.exceptions import BotoCoreError, ClientError


# Bloque de razonamiento de Qwen3 por si aparece en la respuesta
THINK_PATTERN = re.compile(r"<think>.*?</think>", re.DOTALL)


class TeaserError(Exception):
    """Error base del modelo de teaser."""


class InvalidInputError(TeaserError, ValueError):
    """El input_text esta vacio, no es texto o supera el limite de caracteres."""


class TeaserGenerationError(TeaserError):
    """El endpoint fallo o devolvio una respuesta sin texto utilizable."""


class TeaserModel:
    """
    Genera el teaser (avance) de un articulo invocando el endpoint de SageMaker
    donde esta desplegado Qwen3-1.7B con los pesos LoRA integrados (qwen_model/deploy.py).

    El servidor (qwen_model/code/inference.py) arma el prompt con la instruccion del entrenamiento,
    recorta a max_input_tokens y genera con decodificacion greedy:
        peticion  {"text": "<input_text>"}
        respuesta {"summary", "input_tokens", "output_tokens", "input_clipped", "cut_off", "generation_s"}
    """

    def __init__(
            self,
            endpoint_name: str = "summarizer-lora",
            region_name="us-east-1",
            max_input_chars=5500,
            client=None
    ):
        if not endpoint_name:
            raise ValueError("Se requiere el nombre del endpoint de SageMaker.")

        self.endpoint_name = endpoint_name
        self.region_name = region_name

        # El texto llega depurado para caber en max_input_tokens=1100 del entrenamiento;
        # 5500 caracteres ~ 1100 tokens con la proporcion mediana (~5 caracteres/token) del corpus
        self.max_input_chars = max_input_chars

        self.client = client or boto3.client("sagemaker-runtime", region_name=region_name)


    def generate(self, input_text: str) -> str:
        """
        Devuelve el teaser generado para input_text.
        Lanza InvalidInputError si el texto no es valido y TeaserGenerationError si falla el endpoint.
        """
        self.validate_input(input_text)

        body = self._invoke(self.build_payload(input_text))
        return self.parse_response(body)


    def validate_input(self, input_text: str) -> None:
        """
        Verificacion simple: texto no vacio y dentro del limite de caracteres.
        """
        if not isinstance(input_text, str):
            raise InvalidInputError("input_text debe ser una cadena de texto.")
        if not input_text.strip():
            raise InvalidInputError("input_text esta vacio.")
        if len(input_text) > self.max_input_chars:
            raise InvalidInputError(
                f"input_text tiene {len(input_text)} caracteres; el maximo es {self.max_input_chars}."
            )


    @staticmethod
    def build_payload(input_text: str) -> dict:
        """
        Cuerpo que espera input_fn de qwen_model/code/inference.py.
        """
        return {"text": input_text.strip()}


    def _invoke(self, payload: dict):
        """
        Llama al endpoint y devuelve el cuerpo de la respuesta ya decodificado como JSON.
        """
        try:
            response = self.client.invoke_endpoint(
                EndpointName=self.endpoint_name,
                ContentType="application/json",
                Accept="application/json",
                Body=json.dumps(payload),
            )
            raw = response["Body"].read()
        except (ClientError, BotoCoreError) as e:
            raise TeaserGenerationError(f"Error invocando el endpoint '{self.endpoint_name}': {e}") from e

        try:
            return json.loads(raw)
        except (TypeError, ValueError) as e:
            raise TeaserGenerationError("El endpoint devolvio una respuesta que no es JSON.") from e


    @staticmethod
    def parse_response(body) -> str:
        """
        Extrae "summary" de la respuesta de output_fn y quita un posible bloque <think>.
        Acepta tambien ["<json>", "application/json"]: lo que devuelve el contenedor de Hugging Face
        cuando output_fn retorna una tupla (version de inference.py desplegada en summarizer-lora).
        """
        if isinstance(body, list) and body and isinstance(body[0], str):
            try:
                body = json.loads(body[0])
            except ValueError as e:
                raise TeaserGenerationError("El endpoint devolvio una lista sin JSON valido.") from e

        text = body.get("summary") if isinstance(body, dict) else None
        if not isinstance(text, str):
            raise TeaserGenerationError(f"Respuesta del endpoint sin 'summary': {str(body)[:200]}")

        text = THINK_PATTERN.sub("", text).strip()
        if not text:
            raise TeaserGenerationError("El endpoint devolvio un teaser vacio.")
        return text
