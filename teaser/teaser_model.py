import json
import re

import boto3
from botocore.exceptions import BotoCoreError, ClientError


# Instruccion usada en el ajuste fino (qwen_model/train_config.json -> "instruction")
DEFAULT_INSTRUCTION = "Summarize the following text in one paragraph of complete sentences."

# Bloque de razonamiento de Qwen3 que puede aparecer al inicio de la respuesta
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
    donde esta desplegado Qwen3-1.7B con los pesos LoRA integrados.
    """

    def __init__(
            self,
            endpoint_name: str,
            region_name="us-east-1",
            max_input_chars=5500,
            max_new_tokens=400,
            temperature=0.7,
            top_p=0.8,
            top_k=20,
            instruction=DEFAULT_INSTRUCTION,
            client=None
    ):
        if not endpoint_name:
            raise ValueError("Se requiere el nombre del endpoint de SageMaker.")

        self.endpoint_name = endpoint_name
        self.region_name = region_name

        # El texto llega depurado para caber en max_input_tokens=1100 del entrenamiento;
        # 5500 caracteres ~ 1100 tokens con la proporcion mediana (~5 caracteres/token) del corpus
        self.max_input_chars = max_input_chars

        # max_new_tokens=400 coincide con max_target_tokens del entrenamiento;
        # temperature/top_p/top_k son los valores recomendados para Qwen3 sin razonamiento
        self.max_new_tokens = max_new_tokens
        self.temperature = temperature
        self.top_p = top_p
        self.top_k = top_k
        self.instruction = instruction

        self.client = client or boto3.client("sagemaker-runtime", region_name=region_name)


    def generate(self, input_text: str) -> str:
        """
        Devuelve el teaser generado para input_text.
        Lanza InvalidInputError si el texto no es valido y TeaserGenerationError si falla el endpoint.
        """
        self.validate_input(input_text)

        prompt = self.build_prompt(input_text)
        body = self._invoke(self.build_payload(prompt))
        return self.parse_response(body, prompt)


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


    def build_prompt(self, input_text: str) -> str:
        """
        Prompt en formato ChatML de Qwen3 con el razonamiento desactivado
        (equivalente a apply_chat_template(..., enable_thinking=False)).
        Se arma aqui para no depender de la plantilla de chat del contenedor.
        """
        user_message = f"{self.instruction}\n\n{input_text.strip()}"
        return (
            f"<|im_start|>user\n{user_message}<|im_end|>\n"
            "<|im_start|>assistant\n<think>\n\n</think>\n\n"
        )


    def build_payload(self, prompt: str) -> dict:
        """
        Cuerpo de la peticion en el formato {"inputs", "parameters"} que aceptan
        los contenedores de generacion de texto de SageMaker (TGI / LMI).
        """
        return {
            "inputs": prompt,
            "parameters": {
                "max_new_tokens": self.max_new_tokens,
                "do_sample": True,
                "temperature": self.temperature,
                "top_p": self.top_p,
                "top_k": self.top_k,
                "return_full_text": False,
                "stop": ["<|im_end|>"],
            },
        }


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
    def parse_response(body, prompt: str = "") -> str:
        """
        Extrae el texto generado de las formas de respuesta habituales:
        [{"generated_text": ...}] (TGI) o {"generated_text": ...} (LMI).
        Quita el prompt si el contenedor lo repite, el bloque <think> y los tokens de fin.
        """
        if isinstance(body, list) and body:
            body = body[0]
        text = body.get("generated_text") if isinstance(body, dict) else None
        if not isinstance(text, str):
            raise TeaserGenerationError(f"Respuesta del endpoint sin 'generated_text': {str(body)[:200]}")

        if prompt and text.startswith(prompt):
            text = text[len(prompt):]

        text = THINK_PATTERN.sub("", text)
        text = text.replace("<|im_end|>", "").replace("<|endoftext|>", "").strip()

        if not text:
            raise TeaserGenerationError("El endpoint devolvio un teaser vacio.")
        return text
