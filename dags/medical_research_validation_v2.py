# -*- coding: utf-8 -*-
"""
DAG de Airflow: Validación y Búsqueda Semántica sobre Weaviate (MedicalResearch)
===============================================================================

Propósito
---------
Este DAG valida el estado de la colección en Weaviate y ejecuta un conjunto de
búsquedas semánticas de prueba para evaluar cobertura y calidad (preparación
para RAG). Incluye:
  1) Comprobación de la colección y métricas básicas de calidad.
  2) Pruebas de búsqueda semántica con consultas representativas.
  3) Consultas avanzadas (multiconcepto y con sesgo temporal).
  4) Simulación de un flujo RAG sencillo (retrieve + síntesis simulada).
  5) Generación de un reporte consolidado con recomendaciones.

Idempotencia y estado
---------------------
El DAG no modifica la colección salvo para leer datos y generar métricas.
Las métricas y resúmenes se escriben en Variables de Airflow para consulta
posterior:
  - collection_health_metrics
  - semantic_search_results
  - search_summary
  - validation_report

Configuración
-------------
Variables de entorno:
  - WEAVIATE_URL, WEAVIATE_API_KEY (opcional)

Variables de Airflow (modificables en la UI):
  - med_collection_name (nombre de la colección en Weaviate)
  - med_embedding_model (modelo de embeddings para consultas)
  - med_search_top_k (número de resultados por consulta)
  - med_search_threshold (umbral de relevancia esperado)
  - med_validation_seed (semilla para reproducibilidad)

Recomendación operativa
-----------------------
En producción, preferir imágenes con dependencias preinstaladas. La tarea
install_packages existe para entornos de prueba o desarrollo.
"""

import os
import sys
import json
import time
import random
import subprocess
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.models import Variable

# ---------------------------
# Configuración global (ENV + Variables)
# ---------------------------
WEAVIATE_URL = os.getenv("WEAVIATE_URL", "http://weaviate.weaviate.svc.cluster.local:8080")
WEAVIATE_API_KEY = os.getenv("WEAVIATE_API_KEY")  # opcional

VAR_COLLECTION = Variable.get("med_collection_name", default_var="MedicalResearch")
VAR_EMB_MODEL = Variable.get("med_embedding_model", default_var="pritamdeka/S-PubMedBert-MS-MARCO")
VAR_TOP_K = int(Variable.get("med_search_top_k", default_var="3"))
VAR_THRESHOLD = float(Variable.get("med_search_threshold", default_var="0.7"))  # se aplica a certainty o score derivado
VAR_SEED = int(Variable.get("med_validation_seed", default_var="7"))

# Consultas de prueba (cobertura de dominios comunes en diabetes)
TEST_QUERIES: List[Dict[str, Any]] = [
    {"query": "What are the latest treatments for Type 2 diabetes?",
     "expected_keywords": ["diabetes", "treatment", "metformin", "insulin"],
     "category": "treatment"},
    {"query": "Side effects of metformin in diabetic patients",
     "expected_keywords": ["metformin", "side effects", "adverse"],
      "category": "pharmacology"},
    {"query": "Relationship between diabetes and cardiovascular disease",
     "expected_keywords": ["diabetes", "cardiovascular", "heart", "risk"],
     "category": "comorbidity"},
    {"query": "HbA1c levels and glycemic control monitoring",
     "expected_keywords": ["HbA1c", "glycemic", "glucose", "monitoring"],
     "category": "diagnostics"},
    {"query": "Lifestyle interventions for diabetes prevention",
     "expected_keywords": ["lifestyle", "prevention", "exercise", "diet"],
     "category": "prevention"},
]

default_args = {
    'owner': 'healthcare-team',
    'depends_on_past': False,
    'start_date': datetime(2025, 1, 1),
    'email_on_failure': False,
    'email_on_retry': False,
    'retries': 1,
    'retry_delay': timedelta(minutes=2),
}

# ---------------------------
# Utilidades
# ---------------------------
def install_validation_packages():
    """
    Instala paquetes necesarios para validación. En producción se recomienda
    incluir estos paquetes en la imagen del worker y omitir esta tarea.
    """
    packages = [
        'weaviate-client>=3.25.0',
        'sentence-transformers>=2.3.0',
        'tabulate',
        'matplotlib',
        'pandas',
    ]
    for package in packages:
        try:
            subprocess.check_call([sys.executable, '-m', 'pip', 'install', '--quiet', package])
            print(f"[deps] Installed {package}")
        except Exception as e:
            print(f"[deps] Failed to install {package}: {e}")

def _weaviate_client():
    """
    Devuelve un cliente de Weaviate con autenticación por API Key si está
    configurada. Define un timeout para conexión y lectura.
    """
    import weaviate
    try:
        from weaviate.auth import AuthApiKey
    except Exception:
        AuthApiKey = None

    auth = AuthApiKey(api_key=WEAVIATE_API_KEY) if (WEAVIATE_API_KEY and AuthApiKey) else None
    client = weaviate.Client(
        url=WEAVIATE_URL,
        auth_client_secret=auth,
        timeout_config=(10, 120),  # connect, read
    )
    return client

def _safe_len(x):
    """Retorna len(x) o 0 si no es posible calcular la longitud."""
    try:
        return len(x)
    except Exception:
        return 0

def _score_from_additional(additional: Dict[str, Any]) -> float:
    """
    Unifica la puntuación devuelta por Weaviate:
      - Si hay 'certainty' (0..1), se usa directamente (mayor es mejor).
      - Si hay 'distance' (cosine), se deriva score = 1 - distance (acotado a 0..1).
      - En ausencia de ambas, retorna 0.0.
    """
    if not additional:
        return 0.0
    if 'certainty' in additional and isinstance(additional['certainty'], (int, float)):
        return float(additional['certainty'])
    if 'distance' in additional and isinstance(additional['distance'], (int, float)):
        d = float(additional['distance'])
        score = 1.0 - max(0.0, min(1.0, d))
        return score
    return 0.0

def _print_kv_table(title: str, dct: Dict[str, Any]):
    """
    Imprime pares clave-valor con un encabezado. Salida simple y legible en logs.
    """
    print("\n" + title)
    print("-" * len(title))
    for k, v in dct.items():
        print(f"{k:>24}: {v}")

# ---------------------------
# Tareas
# ---------------------------
def validate_collection_health():
    """
    Comprueba la existencia de la colección en Weaviate y calcula métricas
    básicas de calidad sobre una muestra:
      - Total de documentos.
      - Porcentaje con abstract y con términos MeSH.
      - Longitud media de los abstracts.
      - Número de journals distintos en la muestra.
    Guarda las métricas en la Variable 'collection_health_metrics'.
    """
    import traceback
    random.seed(VAR_SEED)

    try:
        client = _weaviate_client()
        collection_name = VAR_COLLECTION

        print("=" * 60)
        print("MEDICAL RESEARCH COLLECTION HEALTH CHECK")
        print("=" * 60)

        # Existencia del esquema
        schema = client.schema.get()
        exists = any(c['class'] == collection_name for c in schema.get('classes', []))
        if not exists:
            raise ValueError(f"Collection '{collection_name}' not found. Ingerir documentos primero.")

        print(f"[health] Collection '{collection_name}' exists")

        # Conteo de documentos
        agg = client.query.aggregate(collection_name).with_meta_count().do()
        total_docs = agg['data']['Aggregate'][collection_name][0]['meta']['count']
        print(f"[health] Total documents: {total_docs}")
        if total_docs == 0:
            raise ValueError("Collection is empty. Ingerir documentos primero.")

        # Muestra aleatoria (limit 5)
        fields = ['pmid', 'title', 'abstract', 'mesh_terms', 'publication_date', 'journal']
        sample = client.query.get(collection_name, fields).with_limit(5).do()
        sample_docs = sample['data']['Get'].get(collection_name, [])

        # Métricas sobre la muestra
        docs_with_abstracts = sum(1 for d in sample_docs if (d.get('abstract') or '').strip())
        docs_with_mesh = sum(1 for d in sample_docs if _safe_len(d.get('mesh_terms')) > 0)
        avg_abstract_len = 0
        if sample_docs:
            lens = [len((d.get('abstract') or '')) for d in sample_docs]
            avg_abstract_len = sum(lens) / len(lens)

        unique_journals = len(set((d.get('journal') or 'Unknown') for d in sample_docs))
        quality = {
            'total_documents': total_docs,
            'sample_size': len(sample_docs),
            'docs_with_abstracts': docs_with_abstracts,
            'docs_with_mesh_terms': docs_with_mesh,
            'avg_abstract_length': round(avg_abstract_len, 1) if sample_docs else 0,
            'unique_journals': unique_journals,
        }

        _print_kv_table("Quality Metrics", quality)

        # Mostrar hasta 3 documentos de ejemplo
        print("\nSample Documents:")
        for i, doc in enumerate(sample_docs[:3], 1):
            title = (doc.get('title') or 'N/A').strip()
            abstract = (doc.get('abstract') or '').strip()
            mesh = doc.get('mesh_terms') or []
            pmid = doc.get('pmid', 'N/A')
            journal = doc.get('journal', 'N/A')
            print(f"\n   {i}. PMID: {pmid}")
            print(f"      Title: {title[:90]}{'...' if len(title) > 90 else ''}")
            print(f"      Journal: {journal}")
            print(f"      MeSH Terms: {', '.join(mesh[:5])}")

        Variable.set("collection_health_metrics", json.dumps(quality))
        return quality

    except Exception as e:
        print("[health] Error validating collection:", str(e))
        traceback.print_exc()
        raise

def perform_semantic_searches(**context):
    """
    Ejecuta búsquedas semánticas (near_vector) para un conjunto de consultas
    de prueba (TEST_QUERIES), resumiendo:
      - Número de resultados por consulta.
      - Mejor puntuación de relevancia (certainty/score).
      - Título y PMID del top-1.
    Guarda resultados en 'semantic_search_results' y un resumen en 'search_summary'.
    """
    import pandas as pd
    from sentence_transformers import SentenceTransformer

    collection_name = VAR_COLLECTION
    top_k = VAR_TOP_K
    threshold = VAR_THRESHOLD

    client = _weaviate_client()

    print("\n" + "=" * 60)
    print("PERFORMING SEMANTIC SEARCHES")
    print("=" * 60)

    # Carga de modelo de embeddings para consultas
    model_name = context.get('params', {}).get('embedding_model', VAR_EMB_MODEL)
    print(f"[search] Loading embedding model: {model_name}")
    try:
        model = SentenceTransformer(model_name)
    except Exception as e:
        print(f"[search] Failed to load {model_name}: {e} | Using fallback all-MiniLM-L6-v2")
        model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")

    results_summary: List[Dict[str, Any]] = []

    for case in TEST_QUERIES:
        query = case['query']
        cat = case['category']
        exp = case['expected_keywords']

        print(f"\n[search] Query: '{query}' | Category: {cat}")
        qvec = model.encode(query).tolist()

        # Ejecución de la búsqueda
        res = client.query \
            .get(collection_name, ['title', 'abstract', 'pmid', 'journal', 'mesh_terms']) \
            .with_near_vector({'vector': qvec}) \
            .with_limit(top_k) \
            .with_additional(['certainty', 'distance']) \
            .do()

        hits = res.get('data', {}).get('Get', {}).get(collection_name, []) or []
        if not hits:
            print("   No results")
            results_summary.append({
                'query': query, 'category': cat, 'results_count': 0,
                'top_score': 0.0, 'top_title': 'None', 'top_pmid': 'None'
            })
            continue

        print(f"   Found {len(hits)} articles")
        top_title, top_pmid, top_score = None, None, 0.0

        for i, art in enumerate(hits, 1):
            add = art.get('_additional', {})
            score = _score_from_additional(add)
            title = (art.get('title') or '').strip()
            abstract = (art.get('abstract') or '').strip()
            pmid = art.get('pmid', 'N/A')
            journal = art.get('journal', 'N/A')

            if i == 1:
                top_title, top_pmid, top_score = title, pmid, score

            print(f"\n   {i}. Title: {title[:80]}{'...' if len(title) > 80 else ''}")
            print(f"      PMID: {pmid} | Journal: {journal} | Score: {score:.3f}")
            if abstract:
                print(f"      Abstract: {abstract[:160]}{'...' if len(abstract) > 160 else ''}")

            # Chequeo de keywords esperadas (heurístico)
            text_l = (title + " " + abstract).lower()
            found = [kw for kw in exp if kw.lower() in text_l]
            if found:
                print(f"      Keywords Found: {', '.join(found)}")

        results_summary.append({
            'query': query, 'category': cat, 'results_count': len(hits),
            'top_score': float(top_score), 'top_title': top_title or 'None', 'top_pmid': top_pmid or 'None'
        })

    # Resumen agregado
    import pandas as pd
    df = pd.DataFrame(results_summary)
    if not df.empty:
        avg_score = float(df['top_score'].mean())
        success = int((df['results_count'] > 0).sum())
    else:
        avg_score, success = 0.0, 0

    summary = {
        'total_queries': len(results_summary),
        'successful_queries': success,
        'avg_relevance_score': round(avg_score, 3),
        'queries_by_category': (df.groupby('category')['results_count'].mean().to_dict() if not df.empty else {}),
        'threshold_used': threshold,
        'top_k': top_k,
    }

    print("\n" + "=" * 60)
    print("SEARCH RESULTS SUMMARY")
    print("=" * 60)
    _print_kv_table("Summary", summary)

    Variable.set("semantic_search_results", json.dumps(results_summary))
    Variable.set("search_summary", json.dumps(summary))
    return results_summary

def test_advanced_queries(**context):
    """
    Pruebas adicionales:
      1) Consulta multiconcepto (varias complicaciones de diabetes).
      2) Consulta con sesgo temporal (hallazgos recientes).
      3) Consulta orientada a fármaco (metformin).
    Estas pruebas ayudan a detectar cobertura y estructura de metadatos (MeSH, fechas).
    """
    from sentence_transformers import SentenceTransformer

    collection_name = VAR_COLLECTION
    client = _weaviate_client()

    print("\n" + "=" * 60)
    print("TESTING ADVANCED QUERIES")
    print("=" * 60)

    model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")

    # 1) Multiconcepto
    print("\n1) Multi-Concept Query Test")
    complex_q = "diabetes complications neuropathy retinopathy nephropathy prevention management"
    vec = model.encode(complex_q).tolist()
    res = client.query.get(collection_name, ['title', 'abstract', 'mesh_terms']) \
        .with_near_vector({'vector': vec}) \
        .with_limit(5).with_additional(['certainty', 'distance']).do()

    hits = res.get('data', {}).get('Get', {}).get(collection_name, []) or []
    if hits:
        all_mesh = []
        for art in hits:
            all_mesh.extend(art.get('mesh_terms') or [])
        uniq = set(all_mesh)
        print(f"   {len(hits)} articles | Unique MeSH: {len(uniq)}")
        print(f"   Top MeSH: {', '.join(list(uniq)[:5])}")

    # 2) Temporal
    print("\n2) Temporal Query Test")
    recent_q = "latest breakthrough diabetes treatment 2024"
    vec = model.encode(recent_q).tolist()
    res = client.query.get(collection_name, ['title', 'publication_date', 'journal']) \
        .with_near_vector({'vector': vec}) \
        .with_limit(5).with_additional(['certainty', 'distance']).do()

    hits = res.get('data', {}).get('Get', {}).get(collection_name, []) or []
    if hits:
        print(f"   {len(hits)} recent-ish articles")
        for art in hits[:3]:
            pub = (art.get('publication_date') or '')[:10]
            title = (art.get('title') or '')[:60]
            print(f"   {pub or 'Unknown'} - {title}{'...' if len(title) == 60 else ''}")

    # 3) Fármaco
    print("\n3) Drug-Specific Query Test")
    drug_q = "metformin mechanism of action glycemic control"
    vec = model.encode(drug_q).tolist()
    res = client.query.get(collection_name, ['title', 'abstract']) \
        .with_near_vector({'vector': vec}) \
        .with_limit(3).with_additional(['certainty', 'distance']).do()

    hits = res.get('data', {}).get('Get', {}).get(collection_name, []) or []
    if hits:
        print(f"   {len(hits)} articles about metformin")
        for i, art in enumerate(hits, 1):
            abstract = (art.get('abstract') or '').lower()
            count = abstract.count('metformin')
            print(f"   Article {i}: 'metformin' mentions = {count}")

    print("\nAdvanced query tests completed")
    return True

def generate_validation_report(**context):
    """
    Construye un reporte consolidado de validación que incluye:
      - Estado de la colección (conteo total y verificación básica).
      - Resultados agregados de las búsquedas semánticas.
      - Recomendaciones simples (más datos, ajuste de modelo, top_k/umbral).
    Genera una visualización textual por categoría en logs y guarda el reporte
    en la Variable 'validation_report'.
    """
    print("\n" + "=" * 60)
    print("GENERATING VALIDATION REPORT")
    print("=" * 60)

    try:
        health = json.loads(Variable.get("collection_health_metrics", "{}"))
        searches = json.loads(Variable.get("semantic_search_results", "[]"))
        summary = json.loads(Variable.get("search_summary", "{}"))

        total_q = summary.get('total_queries', len(searches))
        succ_q = summary.get('successful_queries', sum(1 for r in searches if r.get('results_count', 0) > 0))
        avg_rel = summary.get('avg_relevance_score', 0.0)
        success_rate = (succ_q / total_q) if total_q else 0.0

        report = {
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'collection_status': {
                'name': VAR_COLLECTION,
                'total_documents': health.get('total_documents', 0),
                'health_check': 'PASSED' if health.get('total_documents', 0) > 0 else 'FAILED'
            },
            'search_validation': {
                'total_queries_tested': total_q,
                'successful_queries': succ_q,
                'average_relevance': avg_rel,
                'categories_tested': sorted(list({r.get('category') for r in searches if r.get('category')})),
            },
            'recommendations': [],
            'overall_status': 'OPERATIONAL'
        }

        # Reglas simples de recomendación
        if health.get('total_documents', 0) < 50:
            report['recommendations'].append("Ingerir más documentos para mejorar cobertura.")
            report['overall_status'] = 'NEEDS_MORE_DATA'
        if avg_rel < 0.7:
            report['recommendations'].append("Evaluar un modelo de embeddings médico específico o re-embeddings.")
        if success_rate < 0.8:
            report['recommendations'].append("Existen consultas sin resultados: ampliar dataset o ajustar threshold/top_k.")

        print("\nVALIDATION REPORT SUMMARY")
        print("----------------------------------------")
        print(f"Status: {report['overall_status']}")
        print(f"Documents: {report['collection_status']['total_documents']}")
        print(f"Query Success Rate: {success_rate:.1%}")
        print(f"Avg Relevance Score: {avg_rel:.3f}")

        if report['recommendations']:
            print("\nRecommendations:")
            for rec in report['recommendations']:
                print(f"   - {rec}")

        # Visualización simple por categoría (texto)
        try:
            import pandas as pd
            df = pd.DataFrame(searches)
            if not df.empty:
                cat_stats = df.groupby('category').agg({'results_count': 'mean', 'top_score': 'mean'}).round(2)
                print("\nQuery Performance by Category:")
                for category, row in cat_stats.iterrows():
                    bar_len = int(max(0.0, min(1.0, row['top_score'])) * 20)
                    bar = ('#' * bar_len) + ('-' * (20 - bar_len))
                    print(f"   {category:15} {bar} {row['top_score']:.2f}")
        except Exception as e:
            print(f"[report] Could not build category stats viz: {e}")

        Variable.set("validation_report", json.dumps(report))
        print("\nValidation report stored in Variable 'validation_report'")
        return report

    except Exception as e:
        print(f"[report] Error generating report: {e}")
        raise

def test_rag_with_llm_simulation(**context):
    """
    Simula un flujo RAG básico (retrieve + síntesis simulada).
    Pasos:
      - Codifica una pregunta clínica.
      - Recupera artículos relevantes desde Weaviate.
      - Extrae frases candidatas del abstract (palabras clave clínicas).
      - Emite una respuesta simulada y referencias (PMID/journal).
    Nota: La síntesis está simulada; en producción la respuesta la generaría un LLM.
    """
    from sentence_transformers import SentenceTransformer

    client = _weaviate_client()
    model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")

    print("\n" + "=" * 60)
    print("TESTING RAG PIPELINE SIMULATION")
    print("=" * 60)

    clinical_question = "What is the recommended first-line treatment for newly diagnosed Type 2 diabetes?"
    print(f"\nClinical Question: {clinical_question}")

    qvec = model.encode(clinical_question).tolist()
    res = client.query.get(VAR_COLLECTION, ['title', 'abstract', 'pmid', 'journal']) \
        .with_near_vector({'vector': qvec}).with_limit(3) \
        .with_additional(['certainty', 'distance']).do()

    hits = res.get('data', {}).get('Get', {}).get(VAR_COLLECTION, []) or []
    if not hits:
        print("   No relevant articles found for RAG simulation")
        return False

    print(f"   Retrieved {len(hits)} relevant articles")
    contexts = []
    for i, art in enumerate(hits, 1):
        title = (art.get('title') or '')[:70]
        add = art.get('_additional', {})
        score = _score_from_additional(add)
        print(f"\n   Source {i}: {title} | Score: {score:.3f}")

        abstract = (art.get('abstract') or '')
        sentences = [s.strip() for s in abstract.split('. ') if s.strip()]
        relevant = [s for s in sentences if any(k in s.lower() for k in
                   ['treatment', 'first-line', 'metformin', 'therapy', 'management'])][:2]
        if relevant:
            pmid = art.get('pmid', 'N/A')
            journal = art.get('journal', 'N/A')
            ctx = f"According to {journal} (PMID: {pmid}): " + '. '.join(relevant)
            contexts.append(ctx)
            print(f"   Extract: {relevant[0][:100]}...")

    print("\nSynthesized Answer (simulated):")
    if contexts:
        print("\nSIMULATED RAG RESPONSE")
        print("----------------------------------------")
        print(f"""Based on {len(hits)} medical research articles:

1. Lifestyle: diet and exercise as foundation.
2. Pharmacological: Metformin is preferred initial agent.
3. Monitoring: HbA1c every 3–6 months.

Evidence:
{chr(10).join(f'- {c[:150]}...' for c in contexts[:2])}

Note: Simulated answer; in production, a language model would generate this section using the retrieved context.
""")
        print("\nReferences:")
        for i, art in enumerate(hits, 1):
            print(f"   [{i}] {(art.get('title') or '')[:60]}... (PMID: {art.get('pmid', 'N/A')})")
    return True

# ---------------------------
# Definición del DAG
# ---------------------------
with DAG(
    'medical_research_validation_v2',
    default_args=default_args,
    description='Validate MedicalResearch collection and run semantic/RAG checks',
    schedule=None,
    catchup=False,
    tags=['healthcare', 'validation', 'testing', 'rag', 'weaviate'],
    max_active_runs=1,
    params={'embedding_model': VAR_EMB_MODEL},
) as dag:

    setup_packages = PythonOperator(
        task_id='install_packages',
        python_callable=install_validation_packages,
    )

    validate_health = PythonOperator(
        task_id='validate_collection',
        python_callable=validate_collection_health,
    )

    semantic_search = PythonOperator(
        task_id='semantic_search_tests',
        python_callable=perform_semantic_searches,
    )

    advanced_queries = PythonOperator(
        task_id='advanced_query_tests',
        python_callable=test_advanced_queries,
    )

    rag_test = PythonOperator(
        task_id='rag_pipeline_test',
        python_callable=test_rag_with_llm_simulation,
    )

    generate_report = PythonOperator(
        task_id='generate_validation_report',
        python_callable=generate_validation_report,
    )

    setup_packages >> validate_health >> [semantic_search, advanced_queries] >> rag_test >> generate_report
