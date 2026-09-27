from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import BigInteger, DateTime, ForeignKey, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

from .enums import EstadoPago, MetodoPago, estado_pago_db, metodo_pago_db


class Pago(Base):
    __tablename__ = "pagos"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    pedido_id: Mapped[UUID] = mapped_column(ForeignKey("pedidos.id"), nullable=False)
    metodo: Mapped[MetodoPago] = mapped_column(metodo_pago_db, nullable=False)
    monto: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    estado: Mapped[EstadoPago] = mapped_column(
        estado_pago_db, nullable=False, default=EstadoPago.PENDIENTE
    )
    referencia_externa: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
