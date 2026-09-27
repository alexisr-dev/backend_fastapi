import uuid
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Numeric, func
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

from .enums import EstadoPedido, estado_pedido_db
from .mesa import Mesa
from .usuario import Usuario


class Pedido(Base):
    __tablename__ = "pedidos"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    mesa_id: Mapped[int] = mapped_column(ForeignKey("mesas.id"), nullable=False)
    mesero_id: Mapped[UUID] = mapped_column(ForeignKey("usuarios.id"), nullable=False)
    estado: Mapped[EstadoPedido] = mapped_column(
        estado_pedido_db, nullable=False, default=EstadoPedido.PENDIENTE
    )
    idempotency_key: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), nullable=False, unique=True
    )
    total: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    mesa: Mapped[Mesa] = relationship()
    mesero: Mapped[Usuario] = relationship()
    detalles: Mapped[list["DetallePedido"]] = relationship(  # noqa: F821
        back_populates="pedido", cascade="all, delete-orphan", order_by="DetallePedido.id"
    )

    @property
    def numero_mesa(self) -> int:
        return self.mesa.numero

    @property
    def mesero_nombre(self) -> str:
        return self.mesero.nombre
