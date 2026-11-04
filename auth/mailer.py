"""
Envío del correo de "Olvidé mi contraseña".
- Con AUTH_MAIL_SENDER definido se envía con Amazon SES (el remitente debe estar verificado en SES
  y el rol de la tarea de ECS necesita ses:SendEmail).
- Sin remitente, en modo local el enlace se escribe en el log de la API para poder probar el flujo;
  fuera de local no se registra el enlace (daría acceso a la cuenta a quien lea los logs).
"""
import logging

logger = logging.getLogger(__name__)


class ResetMailer:
    def __init__(self, sender: str, region_name: str, app_mode: str):
        self.sender = sender
        self.app_mode = app_mode
        self._client = None
        if sender:
            import boto3
            self._client = boto3.client("ses", region_name=region_name)

    def send_reset_link(self, to_email: str, name: str, link: str, minutes: int):
        if not self._client:
            if self.app_mode == "local":
                logger.warning(f"[local] AUTH_MAIL_SENDER no definido; enlace de recuperación para {to_email}: {link}")
            else:
                logger.error("AUTH_MAIL_SENDER no definido: no se pudo enviar el correo de recuperación")
            return

        text = (
            f"Hola {name},\n\n"
            "Recibimos una solicitud para restablecer la contraseña de tu cuenta en DATARA.\n"
            f"Abre este enlace para elegir una nueva (vence en {minutes} minutos):\n\n{link}\n\n"
            "Si no fuiste tú, ignora este correo: tu contraseña no cambiará."
        )
        try:
            self._client.send_email(
                Source=self.sender,
                Destination={"ToAddresses": [to_email]},
                Message={
                    "Subject": {"Data": "DATARA · Restablecer contraseña", "Charset": "UTF-8"},
                    "Body": {"Text": {"Data": text, "Charset": "UTF-8"}},
                },
            )
        except Exception as e:
            # No se propaga: la respuesta al usuario es la misma exista o no la cuenta
            logger.error(f"Error enviando el correo de recuperación: {e}")
