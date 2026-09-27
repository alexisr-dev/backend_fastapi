import time
from collections import defaultdict, deque

from fastapi import HTTPException, status

from .config import settings


class VentanaDeslizante:
    def __init__(self, limite: int, ventana_segundos: int):
        self.limite = limite
        self.ventana = ventana_segundos
        self._marcas: dict[str, deque[float]] = defaultdict(deque)

    def consumir(self, clave: str) -> None:
        ahora = time.monotonic()
        marcas = self._marcas[clave]

        while marcas and ahora - marcas[0] > self.ventana:
            marcas.popleft()

        if len(marcas) >= self.limite:
            espera = int(self.ventana - (ahora - marcas[0])) + 1
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                f"Demasiadas solicitudes. Reintenta en {espera} segundos.",
                headers={"Retry-After": str(espera)},
            )

        marcas.append(ahora)


limitador_pedidos = VentanaDeslizante(
    settings.rate_limit_pedidos, settings.rate_limit_ventana_segundos
)
