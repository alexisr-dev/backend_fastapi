from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class TipoEvento(str, Enum):
    PEDIDO_CREADO = "pedido.creado"
    PEDIDO_ESTADO = "pedido.estado"
    LINEA_ESTADO = "pedido.linea.estado"
    MESA_ESTADO = "mesa.estado"
    PAGO_REGISTRADO = "pago.registrado"
    STOCK_ALERTA = "inventario.alerta"
    CONEXION = "conexion.establecida"


class EventoWS(BaseModel):
    tipo: TipoEvento
    datos: dict[str, Any] = Field(default_factory=dict)
    emitido_en: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def serializar(self) -> dict:
        return self.model_dump(mode="json")


def evento(tipo: TipoEvento, **datos) -> dict:
    return EventoWS(tipo=tipo, datos=datos).serializar()
