import uuid
from decimal import Decimal

from sqlalchemy import select

from app.models import Mesa, Pago


async def crear_pedido(cliente, datos, cabeceras, cantidad_plato=1, cantidad_bebida=0):
    lineas = [{"producto_id": datos["plato"].id, "cantidad": cantidad_plato}]
    if cantidad_bebida:
        lineas.append({"producto_id": datos["bebida"].id, "cantidad": cantidad_bebida})
    respuesta = await cliente.post(
        "/api/v1/pedidos",
        json={
            "mesa_id": datos["mesa"].id,
            "idempotency_key": str(uuid.uuid4()),
            "lineas": lineas,
        },
        headers=cabeceras,
    )
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()


async def entregar(cliente, pedido_id, cabeceras_mesero, cabeceras_cocina):
    await cliente.post(f"/api/v1/cocina/pedidos/{pedido_id}/preparar", headers=cabeceras_cocina)
    await cliente.post(f"/api/v1/cocina/pedidos/{pedido_id}/listo", headers=cabeceras_cocina)
    await cliente.patch(
        f"/api/v1/pedidos/{pedido_id}/estado",
        json={"estado": "entregado"},
        headers=cabeceras_mesero,
    )


async def test_la_cuenta_suma_los_pedidos_no_cancelados_de_la_mesa(
    cliente, datos, cabeceras_mesero
):
    await crear_pedido(cliente, datos, cabeceras_mesero, cantidad_plato=1)  # 20.00
    await crear_pedido(cliente, datos, cabeceras_mesero, cantidad_plato=2)  # 40.00

    respuesta = await cliente.get(
        f"/api/v1/mesas/{datos['mesa'].id}/cuenta", headers=cabeceras_mesero
    )
    assert respuesta.status_code == 200
    cuenta = respuesta.json()
    assert Decimal(cuenta["total"]) == Decimal("60.00")
    assert Decimal(cuenta["pagado"]) == Decimal("0")
    assert Decimal(cuenta["saldo"]) == Decimal("60.00")
    assert len(cuenta["pedidos"]) == 2


async def test_un_pago_parcial_deja_saldo_y_la_mesa_ocupada(
    cliente, sesion, datos, cabeceras_mesero
):
    await crear_pedido(cliente, datos, cabeceras_mesero, cantidad_plato=2)  # 40.00

    respuesta = await cliente.post(
        f"/api/v1/mesas/{datos['mesa'].id}/pagos",
        json={"metodo": "efectivo", "monto": "15.00"},
        headers=cabeceras_mesero,
    )
    assert respuesta.status_code == 201, respuesta.text
    cuenta = respuesta.json()
    assert Decimal(cuenta["pagado"]) == Decimal("15.00")
    assert Decimal(cuenta["saldo"]) == Decimal("25.00")

    mesa = await sesion.get(Mesa, datos["mesa"].id)
    await sesion.refresh(mesa)
    assert mesa.estado == "ocupada"


async def test_pagos_sucesivos_con_distintos_metodos_hasta_saldo_cero(
    cliente, datos, cabeceras_mesero
):
    await crear_pedido(cliente, datos, cabeceras_mesero, cantidad_plato=1)  # 20.00

    await cliente.post(
        f"/api/v1/mesas/{datos['mesa'].id}/pagos",
        json={"metodo": "efectivo", "monto": "8.00"},
        headers=cabeceras_mesero,
    )
    respuesta = await cliente.post(
        f"/api/v1/mesas/{datos['mesa'].id}/pagos",
        json={"metodo": "yape", "monto": "12.00"},
        headers=cabeceras_mesero,
    )
    assert respuesta.status_code == 201
    cuenta = respuesta.json()
    assert Decimal(cuenta["saldo"]) == Decimal("0")
    metodos = {p["metodo"] for p in cuenta["pagos"]}
    assert metodos == {"efectivo", "yape"}


async def test_un_pago_que_excede_el_saldo_devuelve_400(cliente, datos, cabeceras_mesero):
    await crear_pedido(cliente, datos, cabeceras_mesero, cantidad_plato=1)  # 20.00

    respuesta = await cliente.post(
        f"/api/v1/mesas/{datos['mesa'].id}/pagos",
        json={"metodo": "tarjeta", "monto": "25.00"},
        headers=cabeceras_mesero,
    )
    assert respuesta.status_code == 400
    assert respuesta.json()["code"] == "pago_excedido"


async def test_un_metodo_de_pago_invalido_devuelve_422(cliente, datos, cabeceras_mesero):
    await crear_pedido(cliente, datos, cabeceras_mesero, cantidad_plato=1)

    respuesta = await cliente.post(
        f"/api/v1/mesas/{datos['mesa'].id}/pagos",
        json={"metodo": "bitcoin", "monto": "5.00"},
        headers=cabeceras_mesero,
    )
    assert respuesta.status_code == 422


async def test_cobrar_una_mesa_sin_pedidos_devuelve_400(cliente, datos, cabeceras_mesero):
    respuesta = await cliente.post(
        f"/api/v1/mesas/{datos['mesa'].id}/pagos",
        json={"metodo": "efectivo", "monto": "5.00"},
        headers=cabeceras_mesero,
    )
    assert respuesta.status_code == 400
    assert respuesta.json()["code"] == "sin_pedidos"


async def test_liberar_con_saldo_pendiente_devuelve_409(
    cliente, sesion, datos, cabeceras_mesero, cabeceras_cocina
):
    pedido = await crear_pedido(cliente, datos, cabeceras_mesero, cantidad_plato=1)
    await entregar(cliente, pedido["id"], cabeceras_mesero, cabeceras_cocina)

    respuesta = await cliente.post(
        f"/api/v1/mesas/{datos['mesa'].id}/liberar", json={}, headers=cabeceras_mesero
    )
    assert respuesta.status_code == 409

    mesa = await sesion.get(Mesa, datos["mesa"].id)
    await sesion.refresh(mesa)
    assert mesa.estado == "ocupada"


async def test_liberar_sin_saldo_pone_la_mesa_libre(
    cliente, sesion, datos, cabeceras_mesero, cabeceras_cocina
):
    pedido = await crear_pedido(cliente, datos, cabeceras_mesero, cantidad_plato=1)  # 20.00
    await entregar(cliente, pedido["id"], cabeceras_mesero, cabeceras_cocina)
    await cliente.post(
        f"/api/v1/mesas/{datos['mesa'].id}/pagos",
        json={"metodo": "efectivo", "monto": "20.00"},
        headers=cabeceras_mesero,
    )

    respuesta = await cliente.post(
        f"/api/v1/mesas/{datos['mesa'].id}/liberar", json={}, headers=cabeceras_mesero
    )
    assert respuesta.status_code == 200
    assert respuesta.json()["estado"] == "libre"

    mesa = await sesion.get(Mesa, datos["mesa"].id)
    await sesion.refresh(mesa)
    assert mesa.estado == "libre"


async def test_un_mesero_no_puede_forzar_la_liberacion(
    cliente, datos, cabeceras_mesero, cabeceras_cocina
):
    pedido = await crear_pedido(cliente, datos, cabeceras_mesero, cantidad_plato=1)
    await entregar(cliente, pedido["id"], cabeceras_mesero, cabeceras_cocina)

    respuesta = await cliente.post(
        f"/api/v1/mesas/{datos['mesa'].id}/liberar",
        json={"forzar": True, "motivo": "se fueron sin pagar"},
        headers=cabeceras_mesero,
    )
    assert respuesta.status_code == 403


async def test_un_admin_fuerza_la_liberacion_y_registra_el_cierre(
    cliente, sesion, datos, cabeceras_mesero, cabeceras_cocina, cabeceras_admin
):
    pedido = await crear_pedido(cliente, datos, cabeceras_mesero, cantidad_plato=1)  # 20.00
    await entregar(cliente, pedido["id"], cabeceras_mesero, cabeceras_cocina)

    respuesta = await cliente.post(
        f"/api/v1/mesas/{datos['mesa'].id}/liberar",
        json={"forzar": True, "motivo": "se fueron sin pagar"},
        headers=cabeceras_admin,
    )
    assert respuesta.status_code == 200
    cuenta = respuesta.json()
    assert cuenta["estado"] == "libre"
    assert Decimal(cuenta["saldo"]) == Decimal("0")

    mesa = await sesion.get(Mesa, datos["mesa"].id)
    await sesion.refresh(mesa)
    assert mesa.estado == "libre"

    pagos = await sesion.execute(
        select(Pago).where(Pago.pedido_id == uuid.UUID(pedido["id"]))
    )
    filas = list(pagos.scalars())
    assert any(
        (fila.referencia_externa or "").startswith("cierre_forzado") for fila in filas
    )


async def test_la_cuenta_de_una_mesa_inexistente_devuelve_404(cliente, datos, cabeceras_mesero):
    respuesta = await cliente.get("/api/v1/mesas/999999/cuenta", headers=cabeceras_mesero)
    assert respuesta.status_code == 404


async def test_el_listado_de_mesas_muestra_el_saldo_por_cobrar(
    cliente, datos, cabeceras_mesero, cabeceras_cocina
):
    pedido = await crear_pedido(cliente, datos, cabeceras_mesero, cantidad_plato=1)  # 20.00
    await entregar(cliente, pedido["id"], cabeceras_mesero, cabeceras_cocina)

    def fila_de_la_mesa(cuerpo):
        return next(m for m in cuerpo if m["id"] == datos["mesa"].id)

    antes = fila_de_la_mesa((await cliente.get("/api/v1/mesas", headers=cabeceras_mesero)).json())
    assert antes["estado"] == "ocupada"
    assert float(antes["total_en_curso"]) == 20.0

    await cliente.post(
        f"/api/v1/mesas/{datos['mesa'].id}/pagos",
        json={"metodo": "yape", "monto": "12.00"},
        headers=cabeceras_mesero,
    )
    despues = fila_de_la_mesa((await cliente.get("/api/v1/mesas", headers=cabeceras_mesero)).json())
    assert float(despues["total_en_curso"]) == 8.0
