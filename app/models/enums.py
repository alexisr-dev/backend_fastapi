from enum import Enum

from sqlalchemy.dialects.postgresql import ENUM


class TextoEnum(str, Enum):
    def __str__(self) -> str:
        return self.value


class EstadoMesa(TextoEnum):
    LIBRE = "libre"
    OCUPADA = "ocupada"
    RESERVADA = "reservada"


class EstadoPedido(TextoEnum):
    PENDIENTE = "pendiente"
    PREPARANDO = "preparando"
    LISTO = "listo"
    ENTREGADO = "entregado"
    CANCELADO = "cancelado"


class EstadoItemPedido(TextoEnum):
    PENDIENTE = "pendiente"
    PREPARANDO = "preparando"
    LISTO = "listo"
    ENTREGADO = "entregado"
    CANCELADO = "cancelado"


class TipoMovimiento(TextoEnum):
    ENTRADA = "entrada"
    SALIDA = "salida"
    AJUSTE = "ajuste"


class MotivoMovimiento(TextoEnum):
    VENTA = "venta"
    COMPRA = "compra"
    AJUSTE_MANUAL = "ajuste_manual"
    MERMA = "merma"


class MetodoPago(TextoEnum):
    EFECTIVO = "efectivo"
    YAPE = "yape"
    PLIN = "plin"
    TARJETA = "tarjeta"
    MERCADO_PAGO = "mercado_pago"


class EstadoPago(TextoEnum):
    PENDIENTE = "pendiente"
    CONFIRMADO = "confirmado"
    RECHAZADO = "rechazado"


TRANSICIONES_PEDIDO: dict[EstadoPedido, set[EstadoPedido]] = {
    EstadoPedido.PENDIENTE: {EstadoPedido.PREPARANDO, EstadoPedido.CANCELADO},
    EstadoPedido.PREPARANDO: {EstadoPedido.LISTO, EstadoPedido.CANCELADO},
    EstadoPedido.LISTO: {EstadoPedido.ENTREGADO},
    EstadoPedido.ENTREGADO: set(),
    EstadoPedido.CANCELADO: set(),
}


def _pg_enum(nombre: str, enumeracion: type[TextoEnum]) -> ENUM:
    return ENUM(
        *[miembro.value for miembro in enumeracion],
        name=nombre,
        create_type=False,
        native_enum=True,
    )


estado_mesa_db = _pg_enum("estado_mesa", EstadoMesa)
estado_pedido_db = _pg_enum("estado_pedido", EstadoPedido)
estado_item_pedido_db = _pg_enum("estado_item_pedido", EstadoItemPedido)
tipo_movimiento_db = _pg_enum("tipo_movimiento", TipoMovimiento)
motivo_movimiento_db = _pg_enum("motivo_movimiento", MotivoMovimiento)
metodo_pago_db = _pg_enum("metodo_pago", MetodoPago)
estado_pago_db = _pg_enum("estado_pago", EstadoPago)
