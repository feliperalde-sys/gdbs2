# GO-Grupo-2
# Entrega 1 — Calidad y Pronóstico
## Caso Integrador: Bebidas del Maipo S.A.

**Asignatura:** Gestión de Producción de Bienes y Servicios  
**Universidad:** Universidad de Santiago de Chile  
**Grupo:** 2

## Descripción

Este repositorio contiene el desarrollo completo de la Entrega 1 del caso integrador Bebidas del Maipo S.A.

El análisis se divide en tres etapas:

- **Parte A:** control estadístico de procesos, capacidad, calidad por atributos y cuantificación económica del sobrellenado.
- **Parte B:** diagnóstico y pronóstico de demanda de los nueve SKU, tratamiento de ventas censuradas, validación temporal y reconciliación jerárquica.
- **Parte C:** consolidación de los parámetros que serán utilizados como entrada para la Entrega 2.

El cuaderno principal es:

`Entrega_1_COMPLETO.ipynb`

Este notebook integra las Partes A, B y C y debe ejecutarse de principio a fin.

---

## Estructura del repositorio

```text
GO-Grupo-2/
│
├── Entrega_1_COMPLETO.ipynb
├── Parte-A/
├── Parte-B/
├── PARTE_C.ipynb
├── datos/
└── README.md
```

---

# Entrega 2 — Planificación de producción e inventario

Modelo de *lot-sizing* capacitado multiproducto para las 13 semanas del horizonte táctico
(28/09/2026 – 21/12/2026), resuelto con PuLP 2.9.0 y CBC.

## Cómo ejecutar (un solo comando)

```bash
pip install -r requirements.txt     # Python 3.11+
python run_entrega2.py              # Partes A, B y C; ~20 minutos (resolución + 10 escenarios)
python run_entrega2.py --rapido     # versión corta: límites de tiempo de solver reducidos
```

`run_entrega2.py` ejecuta los tres notebooks de principio a fin, guarda las salidas dentro de cada
uno y escribe tablas y figuras en `Entrega 2/resultados/`. No requiere Jupyter; los notebooks también
pueden abrirse y ejecutarse en Jupyter o Colab (de arriba hacia abajo, en orden A → B → C).

## Estructura

```text
Entrega 2/
├── entrega2/                         # código del modelo (paquete Python)
│   ├── parametros.py                 # lectura de datos, validación y parámetros por escenario
│   ├── modelo.py                     # MIP por bloques (8 elementos del enunciado), resolución, duales
│   ├── heuristicas.py                # lote por lote y Silver-Meal + simulador con capacidad
│   └── analisis.py                   # costos, cuadro de mando, guardado de soluciones
├── Parte A Formulación/
│   ├── Entrega-2-Parte-A-Formulacion.ipynb
│   └── tabla_traspaso_entrega2.csv   # entrada desde la Entrega 1 (sin modificar)
├── Parte B Resolución y análisis/
│   └── Entrega-2-Parte-B-Resolucion.ipynb
├── Parte C Puente /
│   └── Entrega-2-Parte-C-Puente.ipynb
└── resultados/                       # salidas generadas por el código (CSV, figuras, logs de CBC)
```

## Reglas de datos

- `datos/` y la tabla de traspaso de la Entrega 1 **no se modifican**; toda transformación ocurre en código.
- Los supuestos de modelado están declarados en la Parte A y su impacto se mide en la Parte B.
