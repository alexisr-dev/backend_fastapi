import logging
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from app.core.security import UsuarioAutenticado
from app.models import (
    AlertaInventario,
    DetallePedido,
    EstadoItemPedido,
    EstadoMesa,
    EstadoPedido,
    Mesa,
    Pedido,
    Producto,
)
from app.models.enums import TRANSICIONES_PEDIDO
from app.schemas.pedido import LineaPedidoLeer, PedidoCrear, PedidoLeer

from .idempotency import buscar_pedido_por_clave
from .inventario_client import calcular_consumo, descontar_por_venta, reponer_por_cancelacion

logger = logging.getLogger(__name__)

ESTADOS_ABIERTOS = (EstadoPedido.PENDIENTE, EstadoPedido.PREPARANDO, EstadoPedido.LISTO)


class ReglaNegocioError(Exception):
    def __init__(self, mensaje: str, codigo: str = "regla_negocio"):
        self.mensaje = mensaje
        self.codigo = codigo
        super().__init__(mensaje)


class RecursoNoEncontradoError(Exception):
    pass


def _consulta_pedido():
    return select(Pedido).options(
        joinedload(Pedido.mesa),
        joinedload(Pedido.mesero),
        selectinload(Pedido.detalles).joinedload(DetallePedido.producto),
    )


async def obtener_pedido(sesion: AsyncSession, pedido_id: UUID) -> Pedido:
    resultado = await sesion.execute(_consulta_pedido().where(Pedido.id == pedido_id))
    pedido = resultado.unique().scalar_one_or_none()
    if pedido is None:
        raise RecursoNoEncontradoError(f"No existe el pedido {pedido_id}.")
    return pedido


async def listar_pedidos(
    sesion: AsyncSession,
    *,
    estados: list[EstadoPedido] | None = None,
    mesa_id: int | None = None,
    mesero_id: UUID | None = None,
    limite: int = 50,
) -> list[Pedido]:
    consulta = _consulta_pedido().order_by(Pedido.created_at.desc()).limit(limite)
    if estados:
        consulta = consulta.where(Pedido.estado.in_(estados))
    if mesa_id is not None:
        consulta = consulta.where(Pedido.mesa_id == mesa_id)
    if mesero_id is not None:
        consulta = consulta.where(Pedido.mesero_id == mesero_id)

    resultado = await sesion.execute(consulta)
    return list(resultado.unique().scalars())


def a_schema(pedido: Pedido) -> PedidoLeer:
    return PedidoLeer(
        id=pedido.id,
        mesa_id=pedido.mesa_id,
        mesa_numero=pedido.mesa.numero,
        mesero_id=pedido.mesero_id,
        mesero_nombre=pedido.mesero.nombre,
        estado=pedido.estado,
        total=pedido.total,
        created_at=pedido.created_at,
        updated_at=pedido.updated_at,
        lineas=[
            LineaPedidoLeer(
                id=linea.id,
                producto_id=linea.producto_id,
                producto_nombre=linea.producto.nombre,
                cantidad=linea.cantidad,
                precio_unitario=linea.precio_unitario,
                subtotal=linea.subtotal,
                estado=linea.estado,
                notas=linea.notas,
            )
            for linea in pedido.detalles
        ],
    )


async def crear_pedido(
    sesion: AsyncSession, datos: PedidoCrear, usuario: UsuarioAutenticado
) -> tuple[Pedido, bool, list[AlertaInventario]]:
    existente = await buscar_pedido_por_clave(sesion, datos.idempotency_key)
    if existente is not None:
        return await obtener_pedido(sesion, existente.id), False, []

    mesa = await sesion.get(Mesa, datos.mesa_id, with_for_update=True)
    if mesa is None:
        raise RecursoNoEncontradoError(f"No existe la mesa {datos.mesa_id}.")

    cantidades = {linea.producto_id: linea.cantidad for linea in datos.lineas}
    productos = await _cargar_productos(sesion, list(cantidades))

    pedido = Pedido(
        mesa_id=mesa.id,
        mesero_id=usuario.id,
        estado=EstadoPedido.PENDIENTE,
        idempotency_key=datos.idempotency_key,
        total=Decimal("0"),
    )
    sesion.add(pedido)

    try:
        await sesion.flush()
    except IntegrityError:
        return await _resolver_duplicado(sesion, datos.idempotency_key)

    total = Decimal("0")
    for linea in datos.lineas:
        producto = productos[linea.producto_id]
        total += producto.precio * linea.cantidad
        sesion.add(
            DetallePedido(
                pedido_id=pedido.id,
                producto_id=producto.id,
                cantidad=linea.cantidad,
                precio_unitario=producto.precio,
                estado=EstadoItemPedido.PENDIENTE,
                notas=linea.notas,
            )
        )

    pedido.total = total

    consumo = await calcular_consumo(sesion, cantidades)
    alertas = await descontar_por_venta(
        sesion, consumo, referencia=f"pedido:{pedido.id}", usuario_id=usuario.id
    )

    if mesa.estado == EstadoMesa.LIBRE:
        mesa.estado = EstadoMesa.OCUPADA

    try:
        await sesion.commit()
    except IntegrityError:
        return await _resolver_duplicado(sesion, datos.idempotency_key)

    return await obtener_pedido(sesion, pedido.id), True, alertas


async def _resolver_duplicado(
    sesion: AsyncSession, clave: UUID
) -> tuple[Pedido, bool, list[AlertaInventario]]:
    await sesion.rollback()
    duplicado = await buscar_pedido_por_clave(sesion, clave)
    if duplicado is None:
        raise ReglaNegocioError(
            "No se pudo registrar el pedido por un conflicto de concurrencia.",
            codigo="conflicto_concurrencia",
        )
    logger.info("Pedido duplicado resuelto por idempotencia: %s", duplicado.id)
    return await obtener_pedido(sesion, duplicado.id), False, []


async def cambiar_estado_pedido(
    sesion: AsyncSession, pedido_id: UUID, nuevo_estado: EstadoPedido, usuario: UsuarioAutenticado
) -> Pedido:
    pedido = await sesion.get(Pedido, pedido_id, with_for_update=True)
    if pedido is None:
        raise RecursoNoEncontradoError(f"No existe el pedido {pedido_id}.")

    actual = EstadoPedido(pedido.estado)
    if nuevo_estado == actual:
        return await obtener_pedido(sesion, pedido_id)

    if nuevo_estado not in TRANSICIONES_PEDIDO[actual]:
        raise ReglaNegocioError(
            f"Transicion invalida: '{actual}' no puede pasar a '{nuevo_estado}'.",
            codigo="transicion_invalida",
        )

    mesa = await sesion.get(Mesa, pedido.mesa_id, with_for_update=True)

    if nuevo_estado == EstadoPedido.CANCELADO:
        await _reponer_insumos(sesion, pedido, usuario)

    pedido.estado = nuevo_estado
    await _sincronizar_lineas(sesion, pedido_id, nuevo_estado)
    await sesion.flush()
    await _actualizar_estado_mesa(sesion, mesa)

    await sesion.commit()
    return await obtener_pedido(sesion, pedido_id)


async def cambiar_estado_linea(
    sesion: AsyncSession, pedido_id: UUID, linea_id: int, nuevo_estado: EstadoItemPedido
) -> Pedido:
    linea = await sesion.get(DetallePedido, linea_id, with_for_update=True)
    if linea is None or linea.pedido_id != pedido_id:
        raise RecursoNoEncontradoError("No existe esa linea en el pedido indicado.")

    linea.estado = nuevo_estado
    await sesion.flush()
    await _promover_pedido_segun_lineas(sesion, pedido_id)
    await sesion.commit()
    return await obtener_pedido(sesion, pedido_id)


async def _cargar_productos(sesion: AsyncSession, ids: list[int]) -> dict[int, Producto]:
    resultado = await sesion.execute(select(Producto).where(Producto.id.in_(ids)))
    productos = {producto.id: producto for producto in resultado.unique().scalars()}

    faltantes = set(ids) - set(productos)
    if faltantes:
        raise RecursoNoEncontradoError(
            f"Productos inexistentes: {', '.join(str(i) for i in sorted(faltantes))}."
        )

    inactivos = [p.nombre for p in productos.values() if not p.activo]
    if inactivos:
        raise ReglaNegocioError(
            f"Productos no disponibles: {', '.join(inactivos)}.", codigo="producto_inactivo"
        )

    return productos


async def _reponer_insumos(
    sesion: AsyncSession, pedido: Pedido, usuario: UsuarioAutenticado
) -> None:
    resultado = await sesion.execute(
        select(DetallePedido.producto_id, DetallePedido.cantidad).where(
            DetallePedido.pedido_id == pedido.id
        )
    )
    cantidades = {producto_id: cantidad for producto_id, cantidad in resultado.all()}
    consumo = await calcular_consumo(sesion, cantidades)
    await reponer_por_cancelacion(
        sesion, consumo, referencia=f"cancelacion:{pedido.id}", usuario_id=usuario.id
    )


async def _sincronizar_lineas(
    sesion: AsyncSession, pedido_id: UUID, estado_pedido: EstadoPedido
) -> None:
    equivalencias = {
        EstadoPedido.ENTREGADO: EstadoItemPedido.ENTREGADO,
        EstadoPedido.CANCELADO: EstadoItemPedido.CANCELADO,
        EstadoPedido.LISTO: EstadoItemPedido.LISTO,
    }
    destino = equivalencias.get(estado_pedido)
    if destino is None:
        return

    resultado = await sesion.execute(
        select(DetallePedido).where(DetallePedido.pedido_id == pedido_id)
    )
    for linea in resultado.scalars():
        if linea.estado != EstadoItemPedido.CANCELADO or destino == EstadoItemPedido.CANCELADO:
            linea.estado = destino


async def _promover_pedido_segun_lineas(sesion: AsyncSession, pedido_id: UUID) -> None:
    resultado = await sesion.execute(
        select(DetallePedido.estado, func.count())
        .where(DetallePedido.pedido_id == pedido_id)
        .group_by(DetallePedido.estado)
    )
    conteo = {EstadoItemPedido(estado): total for estado, total in resultado.all()}
    activas = {estado: total for estado, total in conteo.items() if estado != EstadoItemPedido.CANCELADO}

    if not activas:
        return

    pedido = await sesion.get(Pedido, pedido_id)
    actual = EstadoPedido(pedido.estado)

    if set(activas) == {EstadoItemPedido.LISTO} and actual == EstadoPedido.PREPARANDO:
        pedido.estado = EstadoPedido.LISTO
    elif EstadoItemPedido.PREPARANDO in activas and actual == EstadoPedido.PENDIENTE:
        pedido.estado = EstadoPedido.PREPARANDO


async def _actualizar_estado_mesa(sesion: AsyncSession, mesa: Mesa | None) -> None:
    if mesa is None:
        return

    # La mesa solo se libera sola cuando no queda ningun pedido vivo (se cancelo
    # todo, nadie llego a comer). Un pedido 'entregado' sin cobrar la mantiene
    # ocupada: se libera desde POST /mesas/{id}/liberar despues del pago.
    resultado = await sesion.execute(
        select(func.count())
        .select_from(Pedido)
        .where(Pedido.mesa_id == mesa.id)
        .where(Pedido.estado != EstadoPedido.CANCELADO)
    )
    vivos = resultado.scalar_one()

    if vivos == 0 and mesa.estado == EstadoMesa.OCUPADA:
        mesa.estado = EstadoMesa.LIBRE
    elif vivos > 0 and mesa.estado == EstadoMesa.LIBRE:
        mesa.estado = EstadoMesa.OCUPADA
