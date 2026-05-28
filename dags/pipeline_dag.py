from __future__ import annotations

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator

from config import settings
from streaming.kafka_consumer import process_event

default_args = {
    "owner": "data-team",
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}


def _run_placeholder_event() -> None:
    process_event(
        {
            "event": settings.TOPIC_INGEST,
            "schema_version": "1.0",
            "doc_id": "airflow-manual-run",
            "s3_uri": "data/sample/policy.txt",
            "uploaded_by": "airflow",
            "org_id": "internal",
            "metadata": {
                "file_name": "policy.txt",
                "document_type": "policy",
                "language": "vi",
            },
            "permission": {
                "visibility": "private",
                "allowed_roles": ["admin"],
                "allowed_users": [],
                "owner_id": "airflow",
                "org_id": "internal",
            },
            "timestamp": datetime.utcnow().isoformat(),
        }
    )


with DAG(
    dag_id="de_ingestion_pipeline",
    start_date=datetime(2026, 1, 1),
    schedule_interval=None,
    catchup=False,
    max_active_runs=1,
    default_args=default_args,
    tags=["de", "ingestion", "rag"],
) as dag:
    run_pipeline = PythonOperator(
        task_id="run_document_ingestion",
        python_callable=_run_placeholder_event,
    )
