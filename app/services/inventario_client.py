from collections import defaultdict
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AlertaInventario,
    Insumo,
    MotivoMovimiento,
    MovimientoInventario,
    RecetaProducto,
    TipoMovimiento,
)


class StockInsuficienteError(Exception):
    def __init__(self, insumo: str, disponible: Decimal, requerido: Decimal):
        self.insumo = insumo
        self.disponible = disponible
        self.requerido = requerido
        super().__init__(
            f"Stock insuficiente de '{insumo}': disponible {disponible}, requerido {requerido}."
        )


async def calcular_consumo(
    sesion: AsyncSession, cantidades_por_producto: dict[int, int]
) -> dict[int, Decimal]:
    if not cantidades_por_producto:
        return {}

    resultado = await sesion.execute(
        select(RecetaProducto).where(
            RecetaProducto.producto_id.in_(cantidades_por_producto.keys())
        )
    )

    consumo: dict[int, Decimal] = defaultdict(Decimal)
    for linea in resultado.unique().scalars():
        unidades = cantidades_por_producto[linea.producto_id]
        consumo[linea.insumo_id] += linea.cantidad_requerida * unidades
    return dict(consumo)


async def bloquear_insumos(sesion: AsyncSession, insumo_ids: list[int]) -> dict[int, Insumo]:
    if not insumo_ids:
        return {}

    resultado = await sesion.execute(
        select(Insumo)
        .where(Insumo.id.in_(insumo_ids))
        .order_by(Insumo.id)
        .with_for_update()
    )
    return {insumo.id: insumo for insumo in resultado.scalars()}


async def descontar_por_venta(
    sesion: AsyncSession,
    consumo: dict[int, Decimal],
    *,
    referencia: str,
    usuario_id: UUID,
) -> list[AlertaInventario]:
    insumos = await bloquear_insumos(sesion, sorted(consumo))
    alertas: list[AlertaInventario] = []

    for insumo_id in sorted(consumo):
        requerido = consumo[insumo_id]
        insumo = insumos.get(insumo_id)
        if insumo is None:
            raise StockInsuficienteError(f"insumo {insumo_id}", Decimal("0"), requerido)

        if insumo.stock_actual < requerido:
            raise StockInsuficienteError(insumo.nombre, insumo.stock_actual, requerido)

        insumo.stock_actual = insumo.stock_actual - requerido

        sesion.add(
            MovimientoInventario(
                insumo_id=insumo.id,
                tipo=TipoMovimiento.SALIDA,
                motivo=MotivoMovimiento.VENTA,
                cantidad=requerido,
                referencia=referencia,
                usuario_id=usuario_id,
            )
        )

        if insumo.stock_actual <= insumo.stock_minimo:
            alerta = await _crear_alerta_si_falta(sesion, insumo)
            if alerta is not None:
                alertas.append(alerta)

    return alertas


async def reponer_por_cancelacion(
    sesion: AsyncSession,
    consumo: dict[int, Decimal],
    *,
    referencia: str,
    usuario_id: UUID,
) -> None:
    insumos = await bloquear_insumos(sesion, sorted(consumo))

    for insumo_id in sorted(consumo):
        insumo = insumos.get(insumo_id)
        if insumo is None:
            continue

        cantidad = consumo[insumo_id]
        insumo.stock_actual = insumo.stock_actual + cantidad
        sesion.add(
            MovimientoInventario(
                insumo_id=insumo.id,
                tipo=TipoMovimiento.ENTRADA,
                motivo=MotivoMovimiento.AJUSTE_MANUAL,
                cantidad=cantidad,
                referencia=referencia,
                usuario_id=usuario_id,
            )
        )


async def _crear_alerta_si_falta(sesion: AsyncSession, insumo: Insumo) -> AlertaInventario | None:
    existente = await sesion.execute(
        select(AlertaInventario.id)
        .where(AlertaInventario.insumo_id == insumo.id)
        .where(AlertaInventario.atendida.is_(False))
        .limit(1)
    )
    if existente.scalar_one_or_none() is not None:
        return None

    alerta = AlertaInventario(
        insumo_id=insumo.id,
        mensaje=(
            f"Stock bajo de '{insumo.nombre}': {insumo.stock_actual} {insumo.unidad_medida} "
            f"(minimo {insumo.stock_minimo})."
        ),
    )
    sesion.add(alerta)
    return alerta
