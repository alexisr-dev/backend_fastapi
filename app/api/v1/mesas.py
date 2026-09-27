from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select

from app.api.deps import Sesion, Usuario, UsuarioGestion, UsuarioSalon
from app.core.websocket_manager import manager
from app.models import EstadoMesa, EstadoPago, EstadoPedido, Mesa, Pago, Pedido
from app.schemas.mesa import (
    CuentaMesaLeer,
    LiberarMesa,
    MesaActualizar,
    MesaConPedido,
    MesaCrear,
    MesaLeer,
    PagoMesaCrear,
)
from app.schemas.ws_events import TipoEvento, evento
from app.services import pago_service
from app.services.pedido_service import ESTADOS_ABIERTOS

router = APIRouter(prefix="/mesas", tags=["mesas"])


@router.get("", response_model=list[MesaConPedido])
async def listar_mesas(sesion: Sesion, usuario: Usuario, estado: EstadoMesa | None = None):
    # "En curso" = la cuenta abierta de la mesa: pedidos no cancelados y lo que
    # todavia falta cobrar de ellos (total - pagos confirmados). Un pedido
    # entregado sin pagar sigue contando hasta que se libera la mesa.
    pagado_mesa = (
        select(func.coalesce(func.sum(Pago.monto), 0))
        .select_from(Pago)
        .join(Pedido, Pedido.id == Pago.pedido_id)
        .where(Pedido.mesa_id == Mesa.id)
        .where(Pedido.estado != EstadoPedido.CANCELADO)
        .where(Pago.estado == EstadoPago.CONFIRMADO)
        .correlate(Mesa)
        .scalar_subquery()
    )
    consulta = (
        select(
            Mesa,
            func.count(Pedido.id).label("pedidos_activos"),
            (func.coalesce(func.sum(Pedido.total), 0) - pagado_mesa).label("total_en_curso"),
        )
        .outerjoin(
            Pedido,
            (Pedido.mesa_id == Mesa.id) & (Pedido.estado != EstadoPedido.CANCELADO),
        )
        .group_by(Mesa.id)
        .order_by(Mesa.numero)
    )
    if estado is not None:
        consulta = consulta.where(Mesa.estado == estado)

    resultado = await sesion.execute(consulta)
    return [
        MesaConPedido(
            id=mesa.id,
            numero=mesa.numero,
            capacidad=mesa.capacidad,
            estado=mesa.estado,
            created_at=mesa.created_at,
            pedidos_activos=activos,
            total_en_curso=float(total),
        )
        for mesa, activos, total in resultado.all()
    ]


@router.get("/{mesa_id}", response_model=MesaLeer)
async def obtener_mesa(mesa_id: int, sesion: Sesion, usuario: Usuario):
    mesa = await sesion.get(Mesa, mesa_id)
    if mesa is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "La mesa no existe.")
    return mesa


@router.get("/{mesa_id}/cuenta", response_model=CuentaMesaLeer)
async def cuenta_mesa(mesa_id: int, sesion: Sesion, usuario: Usuario):
    """Qué debe la mesa: total de sus pedidos, lo pagado y el saldo pendiente."""
    return await pago_service.resumen_cuenta(sesion, mesa_id)


@router.post(
    "/{mesa_id}/pagos",
    response_model=CuentaMesaLeer,
    status_code=status.HTTP_201_CREATED,
)
async def registrar_pago_mesa(
    mesa_id: int, datos: PagoMesaCrear, sesion: Sesion, usuario: UsuarioSalon
):
    """Registra un pago (parcial o total) contra la cuenta de la mesa. No libera
    la mesa: eso es un paso aparte (`POST /mesas/{id}/liberar`)."""
    cuenta = await pago_service.registrar_pago_mesa(
        sesion,
        mesa_id,
        metodo=datos.metodo,
        monto=datos.monto,
        referencia_externa=datos.referencia_externa,
        usuario=usuario,
    )
    await manager.difundir(
        evento(
            TipoEvento.PAGO_REGISTRADO,
            mesa_id=mesa_id,
            numero=cuenta.numero,
            pagado=str(cuenta.pagado),
            saldo=str(cuenta.saldo),
        )
    )
    return cuenta


@router.post("/{mesa_id}/liberar", response_model=CuentaMesaLeer)
async def liberar_mesa(
    mesa_id: int, datos: LiberarMesa, sesion: Sesion, usuario: UsuarioSalon
):
    """Devuelve la mesa a `libre`. Exige saldo 0; un admin puede forzar el cierre
    con `forzar=true` y el saldo restante se registra como cierre forzado."""
    cuenta = await pago_service.resumen_cuenta(sesion, mesa_id)
    if cuenta.saldo > 0:
        if not datos.forzar:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"La mesa {cuenta.numero} tiene un saldo pendiente de S/ {cuenta.saldo}.",
            )
        if not usuario.es_admin:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "Solo un administrador puede liberar una mesa con saldo pendiente.",
            )

    actualizada = await pago_service.liberar_mesa(
        sesion,
        mesa_id,
        regularizar=cuenta.saldo > 0,
        motivo=datos.motivo,
        usuario=usuario,
    )
    await manager.difundir(
        evento(
            TipoEvento.MESA_ESTADO,
            mesa_id=mesa_id,
            numero=actualizada.numero,
            estado=actualizada.estado,
        )
    )
    return actualizada


@router.post("", response_model=MesaLeer, status_code=status.HTTP_201_CREATED)
async def crear_mesa(datos: MesaCrear, sesion: Sesion, usuario: UsuarioGestion):
    existente = await sesion.execute(select(Mesa.id).where(Mesa.numero == datos.numero))
    if existente.scalar_one_or_none() is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Ya existe la mesa {datos.numero}.")

    mesa = Mesa(numero=datos.numero, capacidad=datos.capacidad, estado=EstadoMesa.LIBRE)
    sesion.add(mesa)
    await sesion.commit()
    await sesion.refresh(mesa)
    return mesa


@router.patch("/{mesa_id}", response_model=MesaLeer)
async def actualizar_mesa(mesa_id: int, datos: MesaActualizar, sesion: Sesion, usuario: Usuario):
    mesa = await sesion.get(Mesa, mesa_id, with_for_update=True)
    if mesa is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "La mesa no existe.")

    if datos.capacidad is not None:
        mesa.capacidad = datos.capacidad

    if datos.estado is not None and datos.estado != mesa.estado:
        if datos.estado == EstadoMesa.LIBRE:
            abiertos = await sesion.execute(
                select(func.count())
                .select_from(Pedido)
                .where(Pedido.mesa_id == mesa_id)
                .where(Pedido.estado.in_(ESTADOS_ABIERTOS))
            )
            if abiertos.scalar_one() > 0:
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    "No se puede liberar una mesa con pedidos en curso.",
                )
            cuenta = await pago_service.resumen_cuenta(sesion, mesa_id)
            if cuenta.saldo > 0:
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    "No se puede liberar una mesa con saldo pendiente. "
                    "Cobra la cuenta o usa POST /mesas/{id}/liberar.",
                )
        mesa.estado = datos.estado

    await sesion.commit()
    await sesion.refresh(mesa)
    await manager.difundir(
        evento(TipoEvento.MESA_ESTADO, mesa_id=mesa.id, numero=mesa.numero, estado=mesa.estado)
    )
    return mesa


@router.delete("/{mesa_id}", status_code=status.HTTP_204_NO_CONTENT)
async def eliminar_mesa(mesa_id: int, sesion: Sesion, usuario: UsuarioGestion):
    mesa = await sesion.get(Mesa, mesa_id)
    if mesa is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "La mesa no existe.")

    pedidos = await sesion.execute(
        select(func.count()).select_from(Pedido).where(Pedido.mesa_id == mesa_id)
    )
    if pedidos.scalar_one() > 0:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "La mesa tiene pedidos historicos y no puede eliminarse."
        )

    await sesion.delete(mesa)
    await sesion.commit()
