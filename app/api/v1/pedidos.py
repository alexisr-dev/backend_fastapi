from uuid import UUID

from fastapi import APIRouter, Query, Response, status
from sqlalchemy import select

from app.api.deps import Sesion, Usuario, UsuarioSalon
from app.core.rate_limit import limitador_pedidos
from app.core.websocket_manager import CANAL_COCINA, CANAL_SALON, manager
from app.models import EstadoPago, EstadoPedido, MetodoPago, Pago
from app.schemas.pedido import (
    CambioEstadoLinea,
    CambioEstadoPedido,
    PagoCrear,
    PedidoCrear,
    PedidoLeer,
)
from app.schemas.ws_events import TipoEvento, evento
from app.services import pedido_service

router = APIRouter(prefix="/pedidos", tags=["pedidos"])


@router.get("", response_model=list[PedidoLeer])
async def listar_pedidos(
    sesion: Sesion,
    usuario: Usuario,
    estado: list[EstadoPedido] | None = Query(default=None),
    mesa_id: int | None = None,
    solo_mios: bool = False,
    limite: int = Query(default=50, ge=1, le=200),
):
    pedidos = await pedido_service.listar_pedidos(
        sesion,
        estados=estado,
        mesa_id=mesa_id,
        mesero_id=usuario.id if solo_mios else None,
        limite=limite,
    )
    return [pedido_service.a_schema(pedido) for pedido in pedidos]


@router.get("/{pedido_id}", response_model=PedidoLeer)
async def obtener_pedido(pedido_id: UUID, sesion: Sesion, usuario: Usuario):
    pedido = await pedido_service.obtener_pedido(sesion, pedido_id)
    return pedido_service.a_schema(pedido)


@router.post("", response_model=PedidoLeer, status_code=status.HTTP_201_CREATED)
async def crear_pedido(
    datos: PedidoCrear, sesion: Sesion, usuario: UsuarioSalon, respuesta: Response
):
    limitador_pedidos.consumir(str(usuario.id))

    pedido, creado, alertas = await pedido_service.crear_pedido(sesion, datos, usuario)
    salida = pedido_service.a_schema(pedido)

    if not creado:
        respuesta.status_code = status.HTTP_200_OK
        return salida

    await manager.difundir(
        evento(TipoEvento.PEDIDO_CREADO, pedido=salida.model_dump(mode="json")),
        (CANAL_COCINA, CANAL_SALON),
    )
    for alerta in alertas:
        await manager.emitir(
            CANAL_SALON,
            evento(TipoEvento.STOCK_ALERTA, insumo_id=alerta.insumo_id, mensaje=alerta.mensaje),
        )
    return salida


@router.patch("/{pedido_id}/estado", response_model=PedidoLeer)
async def cambiar_estado(
    pedido_id: UUID, datos: CambioEstadoPedido, sesion: Sesion, usuario: UsuarioSalon
):
    pedido = await pedido_service.cambiar_estado_pedido(sesion, pedido_id, datos.estado, usuario)
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


@router.patch("/{pedido_id}/lineas/{linea_id}", response_model=PedidoLeer)
async def cambiar_estado_linea(
    pedido_id: UUID,
    linea_id: int,
    datos: CambioEstadoLinea,
    sesion: Sesion,
    usuario: UsuarioSalon,
):
    pedido = await pedido_service.cambiar_estado_linea(sesion, pedido_id, linea_id, datos.estado)
    salida = pedido_service.a_schema(pedido)
    await manager.difundir(
        evento(
            TipoEvento.LINEA_ESTADO,
            pedido_id=str(pedido.id),
            linea_id=linea_id,
            estado=datos.estado,
            pedido=salida.model_dump(mode="json"),
        )
    )
    return salida


@router.post("/{pedido_id}/pagos", status_code=status.HTTP_201_CREATED)
async def registrar_pago(
    pedido_id: UUID, datos: PagoCrear, sesion: Sesion, usuario: UsuarioSalon
):
    pedido = await pedido_service.obtener_pedido(sesion, pedido_id)

    if datos.metodo not in set(MetodoPago):
        raise pedido_service.ReglaNegocioError(
            f"Metodo de pago no soportado: {datos.metodo}.", codigo="metodo_invalido"
        )

    pagado = await sesion.execute(
        select(Pago.monto).where(Pago.pedido_id == pedido_id).where(Pago.estado == EstadoPago.CONFIRMADO)
    )
    acumulado = sum(pagado.scalars(), start=0) + datos.monto
    if acumulado > pedido.total:
        raise pedido_service.ReglaNegocioError(
            f"El pago excede el total del pedido ({pedido.total}).", codigo="pago_excedido"
        )

    pago = Pago(
        pedido_id=pedido_id,
        metodo=MetodoPago(datos.metodo),
        monto=datos.monto,
        estado=EstadoPago.CONFIRMADO,
        referencia_externa=datos.referencia_externa,
    )
    sesion.add(pago)
    await sesion.commit()
    await sesion.refresh(pago)

    return {
        "id": pago.id,
        "pedido_id": str(pago.pedido_id),
        "metodo": pago.metodo,
        "monto": str(pago.monto),
        "estado": pago.estado,
        "saldo_pendiente": str(pedido.total - acumulado),
    }
