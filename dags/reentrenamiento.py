"""DAG de reentrenamiento del modelo de pronóstico de NovaMercado.

Se dispara SOLO desde la API (``POST /admin/reentrenar``), que fija el ``run_id``.

    preparar_datos → entrenar_candidato → evaluar_y_decidir → publicar_resultado
          └──────────────┴──────────────────┴─────────────────────┴──→ marcar_fallo (solo si algo falla:
                                                                       registra el motivo y deja la corrida en 'failed')

* Cada tarea ejecuta un paso de ``novamercado.cli`` con el Python del entorno virtual de ML
  (``/opt/venv-ml``), aislado de las dependencias de Airflow.
* El alias ``vigente`` solo se mueve en la última tarea. Si cualquier paso falla, el modelo
  vigente no cambia y ``marcar_fallo`` deja registrado el motivo en la BD del producto.
"""
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.utils.trigger_rule import TriggerRule

CLI = "/opt/venv-ml/bin/python -m novamercado.cli"
RUN = "--run-id '{{ run_id }}'"

with DAG(
    dag_id="reentrenamiento_modelo",
    description="Reentrena con histórico + observaciones y promueve si mejora el costo",
    start_date=datetime(2024, 1, 1),
    schedule=None,
    catchup=False,
    max_active_runs=1,
    dagrun_timeout=timedelta(minutes=10),
    default_args={"retries": 0, "execution_timeout": timedelta(minutes=8)},
    tags=["novamercado", "mlops"],
    doc_md=__doc__,
) as dag:
    preparar = BashOperator(task_id="preparar_datos", bash_command=f"{CLI} dag-preparar {RUN}")
    entrenar = BashOperator(task_id="entrenar_candidato", bash_command=f"{CLI} dag-entrenar {RUN}")
    decidir = BashOperator(task_id="evaluar_y_decidir", bash_command=f"{CLI} dag-decidir {RUN}")
    publicar = BashOperator(task_id="publicar_resultado", bash_command=f"{CLI} dag-publicar {RUN}")
    # Patrón "watcher": registra el fallo en la BD del producto y luego termina con error
    # para que la ejecución del DAG quede marcada como fallida en Airflow.
    fallo = BashOperator(
        task_id="marcar_fallo",
        bash_command=(f"{CLI} dag-fallo {RUN} --motivo 'Falló una tarea del DAG; el modelo vigente no cambió'; "
                      "echo 'Reentrenamiento fallido: el alias vigente no se modificó'; exit 1"),
        trigger_rule=TriggerRule.ONE_FAILED,
    )

    preparar >> entrenar >> decidir >> publicar
    [preparar, entrenar, decidir, publicar] >> fallo
