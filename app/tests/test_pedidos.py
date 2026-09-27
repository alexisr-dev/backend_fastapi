import uuid
from decimal import Decimal

from sqlalchemy import select

from app.models import Insumo, Mesa, MovimientoInventario


def carga(datos, cantidad_plato=1, cantidad_bebida=0):
    lineas = [{"producto_id": datos["plato"].id, "cantidad": cantidad_plato}]
    if cantidad_bebida:
        lineas.append({"producto_id": datos["bebida"].id, "cantidad": cantidad_bebida})
    return {
        "mesa_id": datos["mesa"].id,
        "idempotency_key": str(uuid.uuid4()),
        "lineas": lineas,
    }


async def test_crear_pedido_calcula_el_total_en_el_servidor(cliente, datos, cabeceras_mesero):
    respuesta = await cliente.post(
        "/api/v1/pedidos", json=carga(datos, 2, 3), headers=cabeceras_mesero
    )
    assert respuesta.status_code == 201
    cuerpo = respuesta.json()
    assert Decimal(cuerpo["total"]) == Decimal("55.00")
    assert cuerpo["estado"] == "pendiente"
    assert len(cuerpo["lineas"]) == 2


async def test_crear_pedido_descuenta_insumos_segun_la_receta(
    cliente, sesion, datos, cabeceras_mesero
):
    stock_previo = datos["insumo_a"].stock_actual

    respuesta = await cliente.post("/api/v1/pedidos", json=carga(datos, 2), headers=cabeceras_mesero)
    assert respuesta.status_code == 201

    insumo = await sesion.get(Insumo, datos["insumo_a"].id)
    await sesion.refresh(insumo)
    assert insumo.stock_actual == stock_previo - Decimal("1.000")


async def test_crear_pedido_registra_los_movimientos_de_inventario(
    cliente, sesion, datos, cabeceras_mesero
):
    respuesta = await cliente.post("/api/v1/pedidos", json=carga(datos, 1), headers=cabeceras_mesero)
    pedido_id = respuesta.json()["id"]

    movimientos = await sesion.execute(
        select(MovimientoInventario).where(
            MovimientoInventario.referencia == f"pedido:{pedido_id}"
        )
    )
    filas = list(movimientos.scalars())
    assert len(filas) == 2
    assert all(fila.tipo == "salida" and fila.motivo == "venta" for fila in filas)


async def test_crear_pedido_ocupa_la_mesa(cliente, sesion, datos, cabeceras_mesero):
    await cliente.post("/api/v1/pedidos", json=carga(datos), headers=cabeceras_mesero)

    mesa = await sesion.get(Mesa, datos["mesa"].id)
    await sesion.refresh(mesa)
    assert mesa.estado == "ocupada"


async def test_stock_insuficiente_devuelve_409_y_revierte_todo(
    cliente, sesion, datos, cabeceras_mesero
):
    stock_previo = datos["insumo_a"].stock_actual

    respuesta = await cliente.post(
        "/api/v1/pedidos", json=carga(datos, 50), headers=cabeceras_mesero
    )
    assert respuesta.status_code == 409
    assert respuesta.json()["code"] == "stock_insuficiente"

    insumo = await sesion.get(Insumo, datos["insumo_a"].id)
    await sesion.refresh(insumo)
    assert insumo.stock_actual == stock_previo

    mesa = await sesion.get(Mesa, datos["mesa"].id)
    await sesion.refresh(mesa)
    assert mesa.estado == "libre"


async def test_un_producto_inactivo_no_se_puede_pedir(cliente, datos, cabeceras_mesero):
    respuesta = await cliente.post(
        "/api/v1/pedidos",
        json={
            "mesa_id": datos["mesa"].id,
            "idempotency_key": str(uuid.uuid4()),
            "lineas": [{"producto_id": datos["inactivo"].id, "cantidad": 1}],
        },
        headers=cabeceras_mesero,
    )
    assert respuesta.status_code == 400
    assert respuesta.json()["code"] == "producto_inactivo"


async def test_una_mesa_inexistente_devuelve_404(cliente, datos, cabeceras_mesero):
    cuerpo = carga(datos)
    cuerpo["mesa_id"] = 999999
    respuesta = await cliente.post("/api/v1/pedidos", json=cuerpo, headers=cabeceras_mesero)
    assert respuesta.status_code == 404


async def test_no_se_admiten_lineas_duplicadas(cliente, datos, cabeceras_mesero):
    respuesta = await cliente.post(
        "/api/v1/pedidos",
        json={
            "mesa_id": datos["mesa"].id,
            "idempotency_key": str(uuid.uuid4()),
            "lineas": [
                {"producto_id": datos["plato"].id, "cantidad": 1},
                {"producto_id": datos["plato"].id, "cantidad": 2},
            ],
        },
        headers=cabeceras_mesero,
    )
    assert respuesta.status_code == 422


async def test_un_pedido_necesita_al_menos_una_linea(cliente, datos, cabeceras_mesero):
    respuesta = await cliente.post(
        "/api/v1/pedidos",
        json={"mesa_id": datos["mesa"].id, "idempotency_key": str(uuid.uuid4()), "lineas": []},
        headers=cabeceras_mesero,
    )
    assert respuesta.status_code == 422


async def test_sin_token_no_hay_acceso(cliente, datos):
    assert (await cliente.get("/api/v1/mesas")).status_code == 401


async def test_un_token_invalido_es_rechazado(cliente, datos):
    respuesta = await cliente.get(
        "/api/v1/mesas", headers={"Authorization": "Bearer no.es.un.token"}
    )
    assert respuesta.status_code == 401


async def test_el_mesero_no_puede_crear_mesas(cliente, datos, cabeceras_mesero):
    respuesta = await cliente.post(
        "/api/v1/mesas", json={"numero": 9999, "capacidad": 4}, headers=cabeceras_mesero
    )
    assert respuesta.status_code == 403
