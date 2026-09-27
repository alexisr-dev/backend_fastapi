"""Cuenta de la mesa: qué se debe, qué se pagó y liberación tras el cobro.

Un pago no se ata a un pedido concreto desde la UI: el mesero cobra "la mesa".
Aquí el `monto` se reparte de forma voraz entre los pedidos con saldo pendiente
(los más antiguos primero) y se inserta un `Pago` confirmado por cada trozo, de
modo que `pagos.pedido_id` sigue siendo válido y el saldo por pedido tiene
sentido para los reportes.
"""

import logging
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import UsuarioAutenticado
from app.models import (
    EstadoMesa,
    EstadoPago,
    EstadoPedido,
    Mesa,
    MetodoPago,
    Pago,
    Pedido,
)
from app.schemas.mesa import CuentaMesaLeer, PagoLeer, PedidoCuentaLeer

from .pedido_service import RecursoNoEncontradoError, ReglaNegocioError

logger = logging.getLogger(__name__)

CERO = Decimal("0")
ESTADOS_ABIERTOS = (EstadoPedido.PENDIENTE, EstadoPedido.PREPARANDO, EstadoPedido.LISTO)


async def _mesa_o_error(sesion: AsyncSession, mesa_id: int, *, bloquear: bool = False) -> Mesa:
    mesa = await sesion.get(Mesa, mesa_id, with_for_update=bloquear)
    if mesa is None:
        raise RecursoNoEncontradoError(f"No existe la mesa {mesa_id}.")
    return mesa


async def _pedidos_no_cancelados(sesion: AsyncSession, mesa_id: int) -> list[Pedido]:
    resultado = await sesion.execute(
        select(Pedido)
        .where(Pedido.mesa_id == mesa_id)
        .where(Pedido.estado != EstadoPedido.CANCELADO)
        .order_by(Pedido.created_at)
    )
    return list(resultado.scalars())


async def _pagos_confirmados(
    sesion: AsyncSession, pedido_ids: list[UUID]
) -> tuple[dict[UUID, Decimal], list[Pago]]:
    if not pedido_ids:
        return {}, []
    resultado = await sesion.execute(
        select(Pago).where(Pago.pedido_id.in_(pedido_ids)).order_by(Pago.created_at)
    )
    pagos = list(resultado.scalars())
    acumulado: dict[UUID, Decimal] = {}
    for pago in pagos:
        if pago.estado == EstadoPago.CONFIRMADO:
            acumulado[pago.pedido_id] = acumulado.get(pago.pedido_id, CERO) + pago.monto
    return acumulado, pagos


def _saldo_mesa(pedidos: list[Pedido], acumulado: dict[UUID, Decimal]) -> Decimal:
    return sum((p.total - acumulado.get(p.id, CERO) for p in pedidos), CERO)


def _asignar_pago(
    sesion: AsyncSession,
    pedidos: list[Pedido],
    acumulado: dict[UUID, Decimal],
    monto: Decimal,
    metodo: MetodoPago,
    referencia_externa: str | None,
) -> None:
    """Reparte `monto` entre los pedidos con saldo, insertando un `Pago` por trozo."""
    restante = monto
    for pedido in pedidos:
        if restante <= CERO:
            break
        saldo_pedido = pedido.total - acumulado.get(pedido.id, CERO)
        if saldo_pedido <= CERO:
            continue
        trozo = min(saldo_pedido, restante)
        sesion.add(
            Pago(
                pedido_id=pedido.id,
                metodo=metodo,
                monto=trozo,
                estado=EstadoPago.CONFIRMADO,
                referencia_externa=referencia_externa,
            )
        )
        acumulado[pedido.id] = acumulado.get(pedido.id, CERO) + trozo
        restante -= trozo


def _a_schema(
    mesa: Mesa,
    pedidos: list[Pedido],
    acumulado: dict[UUID, Decimal],
    pagos: list[Pago],
) -> CuentaMesaLeer:
    total = sum((p.total for p in pedidos), CERO)
    pagado = sum((acumulado.get(p.id, CERO) for p in pedidos), CERO)

    lineas: list[PedidoCuentaLeer] = []
    for pedido in pedidos:
        pagado_pedido = acumulado.get(pedido.id, CERO)
        saldo_pedido = pedido.total - pagado_pedido
        if saldo_pedido > CERO or pedido.estado in ESTADOS_ABIERTOS:
            lineas.append(
                PedidoCuentaLeer(
                    id=pedido.id,
                    estado=pedido.estado,
                    total=pedido.total,
                    pagado=pagado_pedido,
                    saldo=saldo_pedido,
                    created_at=pedido.created_at,
                )
            )

    return CuentaMesaLeer(
        mesa_id=mesa.id,
        numero=mesa.numero,
        estado=mesa.estado,
        total=total,
        pagado=pagado,
        saldo=total - pagado,
        pedidos=lineas,
        pagos=[PagoLeer.model_validate(pago) for pago in pagos],
    )


async def resumen_cuenta(sesion: AsyncSession, mesa_id: int) -> CuentaMesaLeer:
    mesa = await _mesa_o_error(sesion, mesa_id)
    pedidos = await _pedidos_no_cancelados(sesion, mesa_id)
    acumulado, pagos = await _pagos_confirmados(sesion, [p.id for p in pedidos])
    return _a_schema(mesa, pedidos, acumulado, pagos)


async def registrar_pago_mesa(
    sesion: AsyncSession,
    mesa_id: int,
    *,
    metodo: MetodoPago,
    monto: Decimal,
    referencia_externa: str | None,
    usuario: UsuarioAutenticado,
) -> CuentaMesaLeer:
    mesa = await _mesa_o_error(sesion, mesa_id, bloquear=True)
    pedidos = await _pedidos_no_cancelados(sesion, mesa_id)
    if not pedidos:
        raise ReglaNegocioError("La mesa no tiene pedidos que cobrar.", codigo="sin_pedidos")

    acumulado, _ = await _pagos_confirmados(sesion, [p.id for p in pedidos])
    saldo = _saldo_mesa(pedidos, acumulado)
    if monto > saldo:
        raise ReglaNegocioError(
            f"El pago ({monto}) excede el saldo pendiente de la mesa ({saldo}).",
            codigo="pago_excedido",
        )

    _asignar_pago(sesion, pedidos, acumulado, monto, metodo, referencia_externa)
    await sesion.commit()

    logger.info("Pago de %s en mesa %s por %s", monto, mesa_id, usuario.id)
    acumulado, pagos = await _pagos_confirmados(sesion, [p.id for p in pedidos])
    return _a_schema(mesa, pedidos, acumulado, pagos)


async def liberar_mesa(
    sesion: AsyncSession,
    mesa_id: int,
    *,
    regularizar: bool,
    motivo: str | None,
    usuario: UsuarioAutenticado,
) -> CuentaMesaLeer:
    """Pone la mesa en `libre`. Con `regularizar` cubre el saldo restante con un
    `Pago` de cierre forzado (solo lo usa el endpoint tras validar que es admin)."""
    mesa = await _mesa_o_error(sesion, mesa_id, bloquear=True)
    pedidos = await _pedidos_no_cancelados(sesion, mesa_id)
    acumulado, _ = await _pagos_confirmados(sesion, [p.id for p in pedidos])
    saldo = _saldo_mesa(pedidos, acumulado)

    if saldo > CERO and regularizar:
        etiqueta = f"cierre_forzado:{motivo}" if motivo else "cierre_forzado"
        _asignar_pago(sesion, pedidos, acumulado, saldo, MetodoPago.EFECTIVO, etiqueta)
        logger.info("Cierre forzado de mesa %s por %s (saldo %s)", mesa_id, usuario.id, saldo)

    if mesa.estado != EstadoMesa.LIBRE:
        mesa.estado = EstadoMesa.LIBRE

    await sesion.commit()
    acumulado, pagos = await _pagos_confirmados(sesion, [p.id for p in pedidos])
    return _a_schema(mesa, pedidos, acumulado, pagos)
