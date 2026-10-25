/* ============================================================
   Configuración del frontend: URL base de la API
   - Local (localhost o archivo abierto con doble clic): FastAPI en http://localhost:8000
   - AWS (CloudFront): "/api" en el mismo dominio; CloudFront envía /api/* al
     balanceador del servicio ECS mi-cluster/mi-servicio (contenedor mi-app, puerto 8000)
   deploy/publish_frontend.sh puede fijar otra URL con la variable API_URL.
   ============================================================ */
(function () {
  const isLocal =
    location.protocol === "file:" ||
    ["localhost", "127.0.0.1", ""].includes(location.hostname);

  window.APP_CONFIG = {
    API_URL: isLocal ? "http://localhost:8000" : "/api"
  };
})();
