import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import jwt
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select, text

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.core.database import get_session
from app.main import app
from app.models import (
    AlertaInventario,
    Categoria,
    DetallePedido,
    EstadoMesa,
    Insumo,
    Mesa,
    MovimientoInventario,
    Pago,
    Pedido,
    Producto,
    RecetaProducto,
    Usuario,
)

PREFIJO = "pytest_"


def emitir_token(usuario_id: uuid.UUID, rol: str, nombre: str = "Tester") -> str:
    ahora = datetime.now(timezone.utc)
    payload = {
        "token_type": "access",
        "user_id": str(usuario_id),
        "rol": rol,
        "nombre": nombre,
        "email": f"{rol}@test.com",
        "exp": ahora + timedelta(hours=1),
        "iat": ahora,
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


@pytest_asyncio.fixture
async def motor():
    motor = create_async_engine(settings.database_url, poolclass=NullPool)
    yield motor
    await motor.dispose()


@pytest_asyncio.fixture
def fabrica(motor):
    return async_sessionmaker(motor, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture
async def sesion(fabrica):
    async with fabrica() as s:
        yield s


@pytest_asyncio.fixture
async def datos(sesion):
    entorno = await _preparar_entorno(sesion)
    identificadores = {
        "mesas": [entorno["mesa"].id, entorno["otra_mesa"].id],
        "productos": [entorno["plato"].id, entorno["bebida"].id, entorno["inactivo"].id],
        "insumos": [entorno["insumo_a"].id, entorno["insumo_b"].id],
        "usuarios": [entorno[rol].id for rol in ("mesero", "cocina", "admin")],
        "categoria": entorno["categoria"].id,
    }
    yield entorno
    await _limpiar_entorno(sesion, identificadores)


@pytest_asyncio.fixture
async def cliente(fabrica):
    async def sesion_de_prueba():
        async with fabrica() as s:
            try:
                yield s
            except Exception:
                await s.rollback()
                raise

    app.dependency_overrides[get_session] = sesion_de_prueba
    transporte = ASGITransport(app=app)
    async with AsyncClient(transport=transporte, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def cabeceras_mesero(datos):
    return {"Authorization": f"Bearer {emitir_token(datos['mesero'].id, 'mesero')}"}


@pytest.fixture
def cabeceras_cocina(datos):
    return {"Authorization": f"Bearer {emitir_token(datos['cocina'].id, 'cocina')}"}


@pytest.fixture
def cabeceras_admin(datos):
    return {"Authorization": f"Bearer {emitir_token(datos['admin'].id, 'admin')}"}


async def _preparar_entorno(sesion) -> dict:
    usuarios = {}
    for rol in ("mesero", "cocina", "admin"):
        usuario = Usuario(
            id=uuid.uuid4(),
            nombre=f"{PREFIJO}{rol}",
            email=f"{PREFIJO}{rol}_{uuid.uuid4().hex[:8]}@test.com",
            rol=rol,
            activo=True,
            created_at=datetime.now(timezone.utc),
        )
        await sesion.execute(
            text(
                "INSERT INTO usuarios (id, nombre, email, password_hash, rol, activo) "
                "VALUES (:id, :nombre, :email, 'x', :rol, TRUE)"
            ),
            {"id": usuario.id, "nombre": usuario.nombre, "email": usuario.email, "rol": rol},
        )
        usuarios[rol] = usuario

    siguiente = await sesion.execute(text("SELECT COALESCE(MAX(numero), 0) + 1 FROM mesas"))
    numero_base = max(siguiente.scalar_one(), 900)
    mesa = Mesa(numero=numero_base, capacidad=4, estado=EstadoMesa.LIBRE)
    otra_mesa = Mesa(numero=numero_base + 1, capacidad=2, estado=EstadoMesa.LIBRE)
    sesion.add_all([mesa, otra_mesa])

    categoria = Categoria(nombre=f"{PREFIJO}{uuid.uuid4().hex[:8]}")
    sesion.add(categoria)
    await sesion.flush()

    insumo_a = Insumo(
        nombre=f"{PREFIJO}insumo_a_{uuid.uuid4().hex[:8]}",
        unidad_medida="kg",
        stock_actual=Decimal("10.000"),
        stock_minimo=Decimal("2.000"),
        costo_unitario=Decimal("5.00"),
    )
    insumo_b = Insumo(
        nombre=f"{PREFIJO}insumo_b_{uuid.uuid4().hex[:8]}",
        unidad_medida="l",
        stock_actual=Decimal("4.000"),
        stock_minimo=Decimal("3.500"),
        costo_unitario=Decimal("8.00"),
    )
    sesion.add_all([insumo_a, insumo_b])
    await sesion.flush()

    plato = Producto(
        categoria_id=categoria.id,
        nombre=f"{PREFIJO}plato_{uuid.uuid4().hex[:8]}",
        precio=Decimal("20.00"),
        activo=True,
    )
    bebida = Producto(
        categoria_id=categoria.id,
        nombre=f"{PREFIJO}bebida_{uuid.uuid4().hex[:8]}",
        precio=Decimal("5.00"),
        activo=True,
    )
    inactivo = Producto(
        categoria_id=categoria.id,
        nombre=f"{PREFIJO}inactivo_{uuid.uuid4().hex[:8]}",
        precio=Decimal("9.00"),
        activo=False,
    )
    sesion.add_all([plato, bebida, inactivo])
    await sesion.flush()

    sesion.add_all(
        [
            RecetaProducto(producto_id=plato.id, insumo_id=insumo_a.id, cantidad_requerida=Decimal("0.500")),
            RecetaProducto(producto_id=plato.id, insumo_id=insumo_b.id, cantidad_requerida=Decimal("0.200")),
            RecetaProducto(producto_id=bebida.id, insumo_id=insumo_b.id, cantidad_requerida=Decimal("0.100")),
        ]
    )
    await sesion.commit()

    for objeto in (mesa, otra_mesa, insumo_a, insumo_b, plato, bebida, inactivo, categoria):
        await sesion.refresh(objeto)

    return {
        "mesero": usuarios["mesero"],
        "cocina": usuarios["cocina"],
        "admin": usuarios["admin"],
        "mesa": mesa,
        "otra_mesa": otra_mesa,
        "categoria": categoria,
        "insumo_a": insumo_a,
        "insumo_b": insumo_b,
        "plato": plato,
        "bebida": bebida,
        "inactivo": inactivo,
    }


async def _limpiar_entorno(sesion, identificadores: dict) -> None:
    await sesion.rollback()

    mesa_ids = identificadores["mesas"]
    producto_ids = identificadores["productos"]
    insumo_ids = identificadores["insumos"]
    usuario_ids = identificadores["usuarios"]

    pedidos = await sesion.execute(select(Pedido.id).where(Pedido.mesa_id.in_(mesa_ids)))
    pedido_ids = list(pedidos.scalars())

    if pedido_ids:
        await sesion.execute(delete(Pago).where(Pago.pedido_id.in_(pedido_ids)))
        await sesion.execute(delete(DetallePedido).where(DetallePedido.pedido_id.in_(pedido_ids)))
        await sesion.execute(delete(Pedido).where(Pedido.id.in_(pedido_ids)))

    await sesion.execute(delete(MovimientoInventario).where(MovimientoInventario.insumo_id.in_(insumo_ids)))
    await sesion.execute(delete(AlertaInventario).where(AlertaInventario.insumo_id.in_(insumo_ids)))
    await sesion.execute(delete(RecetaProducto).where(RecetaProducto.producto_id.in_(producto_ids)))
    await sesion.execute(delete(Producto).where(Producto.id.in_(producto_ids)))
    await sesion.execute(delete(Insumo).where(Insumo.id.in_(insumo_ids)))
    await sesion.execute(delete(Categoria).where(Categoria.id == identificadores["categoria"]))
    await sesion.execute(delete(Mesa).where(Mesa.id.in_(mesa_ids)))
    await sesion.execute(
        text("DELETE FROM usuarios WHERE id = ANY(:ids)"), {"ids": usuario_ids}
    )
    await sesion.commit()
