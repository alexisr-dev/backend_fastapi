from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Insumo(Base):
    __tablename__ = "insumos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nombre: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    unidad_medida: Mapped[str] = mapped_column(String(20), nullable=False)
    stock_actual: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False, default=0)
    stock_minimo: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False, default=0)
    costo_unitario: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=0)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    @property
    def en_alerta(self) -> bool:
        return self.stock_actual <= self.stock_minimo
