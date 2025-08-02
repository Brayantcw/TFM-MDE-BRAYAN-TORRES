from datetime import datetime, timedelta

import weaviate
from airflow import DAG
from airflow.operators.python import PythonOperator

# Default arguments for the DAG
default_args = {
    'owner': 'airflow',
    'depends_on_past': False,
    'start_date': datetime(2025, 7, 6),
    'email_on_failure': False,
    'email_on_retry': False,
    'retries': 1,
    'retry_delay': timedelta(minutes=5),
}

WEAVIATE_URL    = "http://weaviate.weaviate.svc.cluster.local:8080"   # in-cluster DNS
COLLECTION_NAME = "Article"

def create_collection():
    client = weaviate.Client(url=WEAVIATE_URL)
    schema = {
        "class": COLLECTION_NAME,
        "vectorizer": "none",   # we'll supply our own vectors
        "properties": [
            {"name": "title",       "dataType": ["text"]},
            {"name": "author",      "dataType": ["text"]},
            {"name": "description", "dataType": ["text"]},
        ],
    }

    if not client.schema.contains({"class": COLLECTION_NAME}):
        client.schema.create_class(schema)
        print(f"✔ Created Weaviate class `{COLLECTION_NAME}`")
    else:
        print(f"ℹ Class `{COLLECTION_NAME}` already exists")

with DAG(
    'create_weaviate_collection',
    default_args=default_args,
    description='Create the Weaviate Article collection if missing',
    schedule=timedelta(days=1),
    catchup=False,
    tags=['weaviate', 'schema'],
) as dag:

    create_task = PythonOperator(
        task_id='create_collection',
        python_callable=create_collection,
    )
