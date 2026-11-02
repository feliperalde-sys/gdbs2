"""Entrega 2 - Planificación de producción e inventario (Bebidas del Maipo S.A.).

Módulos:
    parametros  : lectura de datos y construcción de parámetros por escenario.
    modelo      : modelo MIP de lot-sizing capacitado multiproducto (PuLP + CBC).
    heuristicas : políticas de referencia (lote por lote y Silver-Meal) evaluadas
                  con la misma estructura de costos del MIP.
    analisis    : indicadores del cuadro de mando y tablas de resultados.
"""
