from uuid import UUID

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from app.api.deps import Sesion, Usuario, UsuarioCocina
from app.core.websocket_manager import manager
from app.models import DetallePedido, EstadoItemPedido, EstadoPedido, Pedido
from app.schemas.pedido import PedidoLeer
from app.schemas.ws_events import TipoEvento, evento
from app.services import pedido_service

router = APIRouter(prefix="/cocina", tags=["cocina"])

ESTADOS_TABLERO = [EstadoPedido.PENDIENTE, EstadoPedido.PREPARANDO, EstadoPedido.LISTO]


@router.get("/tablero", response_model=dict[str, list[PedidoLeer]])
async def tablero(sesion: Sesion, usuario: Usuario, limite: int = Query(default=60, ge=1, le=200)):
    pedidos = await pedido_service.listar_pedidos(sesion, estados=ESTADOS_TABLERO, limite=limite)
    columnas: dict[str, list[PedidoLeer]] = {estado.value: [] for estado in ESTADOS_TABLERO}
    for pedido in sorted(pedidos, key=lambda p: p.created_at):
        columnas[pedido.estado].append(pedido_service.a_schema(pedido))
    return columnas


@router.get("/metricas")
async def metricas(sesion: Sesion, usuario: Usuario):
    resultado = await sesion.execute(
        select(Pedido.estado, func.count())
        .where(Pedido.estado.in_(ESTADOS_TABLERO))
        .group_by(Pedido.estado)
    )
    por_estado = {estado: total for estado, total in resultado.all()}

    espera = await sesion.execute(
        select(func.avg(func.extract("epoch", func.now() - Pedido.created_at))).where(
            Pedido.estado.in_([EstadoPedido.PENDIENTE, EstadoPedido.PREPARANDO])
        )
    )
    promedio = espera.scalar_one()

    pendientes_items = await sesion.execute(
        select(func.count())
        .select_from(DetallePedido)
        .where(DetallePedido.estado == EstadoItemPedido.PENDIENTE)
    )

    return {
        "pendientes": por_estado.get(EstadoPedido.PENDIENTE, 0),
        "preparando": por_estado.get(EstadoPedido.PREPARANDO, 0),
        "listos": por_estado.get(EstadoPedido.LISTO, 0),
        "items_pendientes": pendientes_items.scalar_one(),
        "espera_promedio_segundos": int(promedio or 0),
    }


@router.post("/pedidos/{pedido_id}/preparar", response_model=PedidoLeer)
async def preparar(pedido_id: UUID, sesion: Sesion, usuario: UsuarioCocina):
    return await _mover(sesion, pedido_id, EstadoPedido.PREPARANDO, usuario)


@router.post("/pedidos/{pedido_id}/listo", response_model=PedidoLeer)
async def marcar_listo(pedido_id: UUID, sesion: Sesion, usuario: UsuarioCocina):
    return await _mover(sesion, pedido_id, EstadoPedido.LISTO, usuario)


async def _mover(sesion, pedido_id: UUID, estado: EstadoPedido, usuario) -> PedidoLeer:
    pedido = await pedido_service.cambiar_estado_pedido(sesion, pedido_id, estado, usuario)
    salida = pedido_service.a_schema(pedido)
    await manager.difundir(
        evento(
            TipoEvento.PEDIDO_ESTADO,
            pedido_id=str(pedido.id),
            estado=pedido.estado,
            mesa_numero=pedido.mesa.numero,
            pedido=salida.model_dump(mode="json"),
        )
    )
    return salida
