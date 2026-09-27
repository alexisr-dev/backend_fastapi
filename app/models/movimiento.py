from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

from .enums import (
    MotivoMovimiento,
    TipoMovimiento,
    motivo_movimiento_db,
    tipo_movimiento_db,
)


class MovimientoInventario(Base):
    __tablename__ = "movimientos_inventario"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    insumo_id: Mapped[int] = mapped_column(ForeignKey("insumos.id"), nullable=False)
    tipo: Mapped[TipoMovimiento] = mapped_column(tipo_movimiento_db, nullable=False)
    motivo: Mapped[MotivoMovimiento] = mapped_column(motivo_movimiento_db, nullable=False)
    cantidad: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    referencia: Mapped[str | None] = mapped_column(String(60))
    usuario_id: Mapped[UUID | None] = mapped_column(ForeignKey("usuarios.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
