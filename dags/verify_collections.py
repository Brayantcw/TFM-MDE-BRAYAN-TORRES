from datetime import datetime, timedelta

import weaviate
from airflow import DAG
from airflow.operators.python import PythonOperator

# Default arguments for the DAG
default_args = {
    'owner': 'airflow',
    'depends_on_past': False,
    'start_date': datetime(2025, 8, 3),
    'email_on_failure': False,
    'email_on_retry': False,
    'retries': 1,
    'retry_delay': timedelta(minutes=5),
}

WEAVIATE_URL = "http://weaviate.weaviate.svc.cluster.local:8080"

def verify_weaviate_collections():
    """Verify and list all Weaviate collections/classes"""
    try:
        client = weaviate.Client(url=WEAVIATE_URL)
        
        # Check if Weaviate is accessible
        if not client.is_ready():
            print("❌ Weaviate is not ready or accessible")
            return
        
        print("✅ Successfully connected to Weaviate")
        
        # Get the complete schema
        schema = client.schema.get()
        
        if not schema.get('classes'):
            print("📋 No collections/classes found in Weaviate")
            return
        
        print(f"📋 Found {len(schema['classes'])} collection(s):")
        print("-" * 50)
        
        for cls in schema['classes']:
            class_name = cls['class']
            vectorizer = cls.get('vectorizer', 'none')
            properties = cls.get('properties', [])
            
            print(f"🗂️  Collection: {class_name}")
            print(f"   Vectorizer: {vectorizer}")
            print(f"   Properties ({len(properties)}):")
            
            for prop in properties:
                prop_name = prop['name']
                prop_type = prop['dataType']
                print(f"     - {prop_name}: {prop_type}")
            
            # Try to get object count
            try:
                result = client.query.aggregate(class_name).with_meta_count().do()
                count = result['data']['Aggregate'][class_name][0]['meta']['count']
                print(f"   Objects: {count}")
            except Exception as e:
                print(f"   Objects: Unable to count ({str(e)})")
            
            print()
        
    except Exception as e:
        print(f"❌ Error connecting to Weaviate: {str(e)}")

def verify_specific_collection():
    """Verify the Article collection specifically"""
    try:
        client = weaviate.Client(url=WEAVIATE_URL)
        
        collection_name = "Article"
        
        if client.schema.contains({"class": collection_name}):
            print(f"✅ Collection '{collection_name}' exists!")
            
            # Get detailed schema
            article_schema = client.schema.get(collection_name)
            print(f"📋 Collection details:")
            print(f"   Class: {article_schema['class']}")
            print(f"   Vectorizer: {article_schema.get('vectorizer', 'none')}")
            print(f"   Properties:")
            
            for prop in article_schema.get('properties', []):
                print(f"     - {prop['name']}: {prop['dataType']}")
            
            # Try to count objects
            try:
                result = client.query.aggregate(collection_name).with_meta_count().do()
                count = result['data']['Aggregate'][collection_name][0]['meta']['count']
                print(f"   Total objects: {count}")
            except Exception as e:
                print(f"   Unable to count objects: {str(e)}")
                
        else:
            print(f"❌ Collection '{collection_name}' does not exist")
            
    except Exception as e:
        print(f"❌ Error verifying collection: {str(e)}")

with DAG(
    'verify_weaviate_collections',
    default_args=default_args,
    description='Verify and list all Weaviate collections',
    schedule=None,  # Manual trigger only
    catchup=False,
    tags=['weaviate', 'verification', 'debug'],
) as dag:

    # Task to list all collections
    list_all_collections = PythonOperator(
        task_id='list_all_collections',
        python_callable=verify_weaviate_collections,
    )
    
    # Task to verify specific Article collection
    verify_article_collection = PythonOperator(
        task_id='verify_article_collection',
        python_callable=verify_specific_collection,
    )
    
    # Set task dependencies
    list_all_collections >> verify_article_collection