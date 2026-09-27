from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Pedido


async def buscar_pedido_por_clave(sesion: AsyncSession, clave: UUID) -> Pedido | None:
    resultado = await sesion.execute(select(Pedido).where(Pedido.idempotency_key == clave))
    return resultado.unique().scalar_one_or_none()
