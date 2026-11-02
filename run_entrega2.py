"""Punto de entrada único de la Entrega 2.

Uso (desde la raíz del repositorio):

    pip install -r requirements.txt
    python run_entrega2.py            # ejecuta Partes A, B y C en orden
    python run_entrega2.py --rapido   # sensibilidades con menos tiempo de solver

Ejecuta los tres notebooks de la Entrega 2 de principio a fin, guarda las salidas
dentro de cada notebook y escribe tablas y figuras en ``Entrega 2/resultados``.
No requiere Jupyter: cada celda se ejecuta en un espacio de nombres compartido,
igual que en un kernel. Los notebooks también pueden abrirse y ejecutarse en
Jupyter o Colab.
"""

from __future__ import annotations

import argparse
import ast
import base64
import contextlib
import io
import json
import os
import sys
import time
import traceback
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
E2 = RAIZ / "Entrega 2"
NOTEBOOKS = [
    E2 / "Parte A Formulación" / "Entrega-2-Parte-A-Formulacion.ipynb",
    E2 / "Parte B Resolución y análisis" / "Entrega-2-Parte-B-Resolucion.ipynb",
    E2 / "Parte C Puente " / "Entrega-2-Parte-C-Puente.ipynb",
]


def _salida_de(obj) -> dict:
    data = {"text/plain": repr(obj)}
    try:
        import pandas as pd
        if isinstance(obj, (pd.DataFrame, pd.Series)):
            df = obj.to_frame() if isinstance(obj, pd.Series) else obj
            data = {"text/html": df.to_html(), "text/plain": df.to_string()}
        elif hasattr(obj, "to_html") and obj.__class__.__name__ == "Styler":
            data = {"text/html": obj.to_html(), "text/plain": obj.data.to_string()}
    except ImportError:
        pass
    return {"output_type": "display_data", "data": data, "metadata": {}}


def ejecutar_notebook(ruta: Path) -> float:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    nb = json.loads(ruta.read_text(encoding="utf-8"))
    salidas: list = []
    buffer = io.StringIO()

    def volcar_texto():
        texto = buffer.getvalue()
        if texto:
            salidas.append({"output_type": "stream", "name": "stdout", "text": texto})
            buffer.seek(0)
            buffer.truncate()

    def display(*objs, **_):
        volcar_texto()
        for obj in objs:
            salidas.append(_salida_de(obj))

    ns = {"__name__": "__main__", "display": display}
    cwd = Path.cwd()
    os.chdir(ruta.parent)
    t0 = time.perf_counter()
    try:
        n = 0
        for celda in nb["cells"]:
            if celda["cell_type"] != "code":
                continue
            n += 1
            salidas.clear()
            fuente = "".join(celda["source"])
            arbol = ast.parse(fuente)
            ultima = arbol.body.pop() if arbol.body and isinstance(arbol.body[-1], ast.Expr) else None
            try:
                with contextlib.redirect_stdout(buffer):
                    exec(compile(arbol, f"<{ruta.name} celda {n}>", "exec"), ns)
                    if ultima is not None:
                        valor = eval(compile(ast.Expression(ultima.value), f"<{ruta.name} celda {n}>", "eval"), ns)
                        if valor is not None:
                            display(valor)
            except Exception:
                volcar_texto()
                print(f"\nError en {ruta.name}, celda de código {n}:\n{fuente[:400]}", file=sys.stderr)
                traceback.print_exc()
                raise
            volcar_texto()
            for num in plt.get_fignums():
                fig = plt.figure(num)
                png = io.BytesIO()
                fig.savefig(png, format="png", dpi=110, bbox_inches="tight")
                salidas.append({"output_type": "display_data", "metadata": {},
                                "data": {"image/png": base64.b64encode(png.getvalue()).decode(),
                                         "text/plain": "<Figure>"}})
            plt.close("all")
            celda["outputs"] = list(salidas)
            celda["execution_count"] = n
    finally:
        os.chdir(cwd)
    ruta.write_text(json.dumps(nb, ensure_ascii=False, indent=1), encoding="utf-8")
    return time.perf_counter() - t0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rapido", action="store_true", help="limita el tiempo de solver en sensibilidades")
    parser.add_argument("--solo", choices=["A", "B", "C"], help="ejecuta una sola parte")
    args = parser.parse_args()
    if args.rapido:
        os.environ["E2_RAPIDO"] = "1"
    sys.path.insert(0, str(E2))
    for ruta in NOTEBOOKS:
        if args.solo and f"Parte-{args.solo}-" not in ruta.name:
            continue
        print(f"Ejecutando {ruta.relative_to(RAIZ)} ...", flush=True)
        seg = ejecutar_notebook(ruta)
        print(f"  listo en {seg:,.0f} s", flush=True)
    print(f"Resultados en {(E2 / 'resultados').relative_to(RAIZ)}")


if __name__ == "__main__":
    main()
