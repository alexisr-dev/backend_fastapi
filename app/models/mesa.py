from datetime import datetime

from sqlalchemy import DateTime, Integer, SmallInteger, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

from .enums import EstadoMesa, estado_mesa_db


class Mesa(Base):
    __tablename__ = "mesas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    numero: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    capacidad: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=4)
    estado: Mapped[EstadoMesa] = mapped_column(
        estado_mesa_db, nullable=False, default=EstadoMesa.LIBRE
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
