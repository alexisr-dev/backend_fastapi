from decimal import Decimal

from sqlalchemy import ForeignKey, Integer, Numeric, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

from .insumo import Insumo
from .producto import Producto


class RecetaProducto(Base):
    __tablename__ = "receta_producto"
    __table_args__ = (UniqueConstraint("producto_id", "insumo_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    producto_id: Mapped[int] = mapped_column(ForeignKey("productos.id"), nullable=False)
    insumo_id: Mapped[int] = mapped_column(ForeignKey("insumos.id"), nullable=False)
    cantidad_requerida: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)

    producto: Mapped[Producto] = relationship(back_populates="receta")
    insumo: Mapped[Insumo] = relationship()
