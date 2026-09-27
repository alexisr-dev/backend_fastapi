from decimal import Decimal
from uuid import UUID

from sqlalchemy import Computed, ForeignKey, Integer, Numeric, SmallInteger, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

from .enums import EstadoItemPedido, estado_item_pedido_db
from .producto import Producto


class DetallePedido(Base):
    __tablename__ = "detalle_pedido"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pedido_id: Mapped[UUID] = mapped_column(ForeignKey("pedidos.id"), nullable=False)
    producto_id: Mapped[int] = mapped_column(ForeignKey("productos.id"), nullable=False)
    cantidad: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    precio_unitario: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    subtotal: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), Computed("cantidad * precio_unitario", persisted=True)
    )
    estado: Mapped[EstadoItemPedido] = mapped_column(
        estado_item_pedido_db, nullable=False, default=EstadoItemPedido.PENDIENTE
    )
    notas: Mapped[str | None] = mapped_column(Text)

    pedido: Mapped["Pedido"] = relationship(back_populates="detalles")  # noqa: F821
    producto: Mapped[Producto] = relationship()
