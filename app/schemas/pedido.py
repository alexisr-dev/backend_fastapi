from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import EstadoItemPedido, EstadoPedido, MetodoPago


class LineaPedidoCrear(BaseModel):
    producto_id: int = Field(gt=0)
    cantidad: int = Field(gt=0, le=99)
    notas: str | None = Field(default=None, max_length=500)


class PedidoCrear(BaseModel):
    mesa_id: int = Field(gt=0)
    idempotency_key: UUID
    lineas: list[LineaPedidoCrear] = Field(min_length=1, max_length=50)

    @field_validator("lineas")
    @classmethod
    def sin_productos_repetidos(cls, lineas):
        vistos = {linea.producto_id for linea in lineas}
        if len(vistos) != len(lineas):
            raise ValueError("No repitas el mismo producto: usa una sola linea con la cantidad total.")
        return lineas


class LineaPedidoLeer(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    producto_id: int
    producto_nombre: str
    cantidad: int
    precio_unitario: Decimal
    subtotal: Decimal
    estado: EstadoItemPedido
    notas: str | None


class PedidoLeer(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    mesa_id: int
    mesa_numero: int
    mesero_id: UUID
    mesero_nombre: str
    estado: EstadoPedido
    total: Decimal
    created_at: datetime
    updated_at: datetime
    lineas: list[LineaPedidoLeer]


class CambioEstadoPedido(BaseModel):
    estado: EstadoPedido


class CambioEstadoLinea(BaseModel):
    estado: EstadoItemPedido


class PagoCrear(BaseModel):
    metodo: MetodoPago
    monto: Decimal = Field(gt=0)
    referencia_externa: str | None = Field(default=None, max_length=120)
