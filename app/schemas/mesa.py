from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import EstadoMesa, EstadoPedido, MetodoPago


class MesaBase(BaseModel):
    numero: int = Field(gt=0)
    capacidad: int = Field(default=4, gt=0, le=50)


class MesaCrear(MesaBase):
    pass


class MesaActualizar(BaseModel):
    capacidad: int | None = Field(default=None, gt=0, le=50)
    estado: EstadoMesa | None = None


class MesaLeer(MesaBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    estado: EstadoMesa
    created_at: datetime


class MesaConPedido(MesaLeer):
    pedidos_activos: int = 0
    total_en_curso: float = 0.0


class PagoMesaCrear(BaseModel):
    metodo: MetodoPago
    monto: Decimal = Field(gt=0)
    referencia_externa: str | None = Field(default=None, max_length=120)


class LiberarMesa(BaseModel):
    forzar: bool = False
    motivo: str | None = Field(default=None, max_length=120)


class PagoLeer(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    pedido_id: UUID
    metodo: MetodoPago
    monto: Decimal
    referencia_externa: str | None
    created_at: datetime


class PedidoCuentaLeer(BaseModel):
    id: UUID
    estado: EstadoPedido
    total: Decimal
    pagado: Decimal
    saldo: Decimal
    created_at: datetime


class CuentaMesaLeer(BaseModel):
    mesa_id: int
    numero: int
    estado: EstadoMesa
    total: Decimal
    pagado: Decimal
    saldo: Decimal
    pedidos: list[PedidoCuentaLeer]
    pagos: list[PagoLeer]
