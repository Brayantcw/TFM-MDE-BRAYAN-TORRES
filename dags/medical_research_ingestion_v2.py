# -*- coding: utf-8 -*-
"""
DAG de Airflow: Ingesta de investigación médica (PubMed) en Weaviate
====================================================================

Propósito
---------
Este DAG realiza un pipeline de ingesta idempotente y por lotes para artículos
de PubMed, generando embeddings y cargándolos en una colección de Weaviate.

Fases del pipeline
------------------
1) setup_dependencies: instala dependencias en tiempo de ejecución (opcional en prod).
2) initialize_weaviate: crea la clase/colección en Weaviate si no existe y muestra métricas.
3) fetch_pubmed_articles: busca y descarga artículos de PubMed, con backoff y paginación.
4) generate_embeddings: genera embeddings con SentenceTransformers en lotes.
5) load_to_weaviate: hace upsert (replace/insert) en Weaviate por PMID estable (UUID v5).

Idempotencia
------------
- Cada objeto se identifica por un UUID estable derivado del PMID.
- Si el PMID ya existe, se reemplaza (actualización) en lugar de duplicar.

Configuración
-------------
- Variables de entorno:
    WEAVIATE_URL, WEAVIATE_API_KEY (opcional),
    ENTREZ_EMAIL, ENTREZ_API_KEY (opcional)
- Variables de Airflow (Variable.get):
    med_ingest_embedding_model (modelo de embeddings),
    med_ingest_retmax (máximo de resultados),
    med_ingest_fetch_batch (tamaño de lote para fetch),
    med_ingest_embed_batch (tamaño de lote para embeddings),
    med_ingest_weav_batch (tamaño de lote para carga),
    med_ingest_seed (semilla de reproducibilidad)

Notas de operación
------------------
- En producción se recomienda instalar dependencias en la imagen del worker
  (evitar instalación dinámica).
- El progreso de embeddings usa barra de progreso en logs de Airflow.
- Se omiten artículos sin abstract (no útiles para embeddings).
"""

import os
import sys
import json
import time
import uuid
import hashlib
import random
import subprocess
from typing import Dict, List, Any
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.models import Variable

# =========================
# Dependencias en tiempo de ejecución (en prod, preferible incluir en la imagen)
# =========================
def install_packages():
    """
    Instala paquetes requeridos en tiempo de ejecución.
    En entornos de producción se recomienda evitar esta fase y
    construir la imagen con las dependencias ya instaladas.
    """
    pkgs = [
        'biopython==1.81',
        'sentence-transformers>=2.2.3',
        'weaviate-client>=3.25.0',
        'numpy',
        'pandas'
    ]
    for p in pkgs:
        try:
            subprocess.check_call([sys.executable, '-m', 'pip', 'install', '--quiet', p])
            print(f"[deps] Installed {p}")
        except Exception as e:
            print(f"[deps] Failed to install {p}: {e}")

# =========================
# Configuración (ENV + Variables de Airflow)
# =========================
WEAVIATE_URL = os.getenv("WEAVIATE_URL", "http://weaviate.weaviate.svc.cluster.local:8080")
WEAVIATE_API_KEY = os.getenv("WEAVIATE_API_KEY")  # opcional
ENTREZ_EMAIL = os.getenv("ENTREZ_EMAIL", "ba.torres@uniandes.edu.co")
ENTREZ_API_KEY = os.getenv("ENTREZ_API_KEY")  # opcional

EMBEDDING_MODEL = Variable.get("med_ingest_embedding_model", default_var="pritamdeka/S-PubMedBert-MS-MARCO")
SEARCH_QUERY_DEFAULT = 'diabetes[MeSH] AND ("2024"[Date - Publication] : "2025"[Date - Publication])'
RETMAX_DEFAULT = int(Variable.get("med_ingest_retmax", default_var="50"))
BATCH_SIZE_FETCH = int(Variable.get("med_ingest_fetch_batch", default_var="20"))
BATCH_SIZE_EMB = int(Variable.get("med_ingest_embed_batch", default_var="32"))
BATCH_SIZE_WEAV = int(Variable.get("med_ingest_weav_batch", default_var="200"))
SEED = int(Variable.get("med_ingest_seed", default_var="7"))

CLASS_NAME = "MedicalResearch"
SCHEMA = {
    "class": CLASS_NAME,
    "description": "Artículos de investigación médica y estudios clínicos",
    "vectorizer": "none",
    "properties": [
        {"name": "pmid", "dataType": ["text"]},
        {"name": "title", "dataType": ["text"]},
        {"name": "abstract", "dataType": ["text"]},
        {"name": "authors", "dataType": ["text[]"]},
        {"name": "journal", "dataType": ["text"]},
        {"name": "publication_date", "dataType": ["date"]},
        {"name": "mesh_terms", "dataType": ["text[]"]},
        {"name": "keywords", "dataType": ["text[]"]},
        {"name": "doi", "dataType": ["text"]},
        {"name": "article_type", "dataType": ["text"]},
        {"name": "citations_count", "dataType": ["int"]},
        {"name": "condition_focus", "dataType": ["text"]},
        {"name": "study_type", "dataType": ["text"]},
        {"name": "sample_size", "dataType": ["int"]},
        {"name": "data_hash", "dataType": ["text"]},
        {"name": "embedding_model", "dataType": ["text"]},
        {"name": "ingestion_timestamp", "dataType": ["date"]},
    ],
}

default_args = {
    'owner': 'healthcare-team',
    'depends_on_past': False,
    'start_date': datetime(2025, 1, 1),
    'email_on_failure': False,
    'email_on_retry': False,
    'retries': 2,
    'retry_delay': timedelta(minutes=5),
}

# =========================
# Helpers
# =========================
def setup_dependencies():
    """
    Instala e importa dependencias en tiempo de ejecución.
    Devuelve True si los imports se realizaron correctamente.
    """
    install_packages()
    global Entrez, SentenceTransformer, weaviate, np
    from Bio import Entrez
    from sentence_transformers import SentenceTransformer
    import weaviate
    import numpy as np
    print("[deps] Runtime dependencies imported")
    return True

def _weaviate_client():
    """
    Crea un cliente de Weaviate con autenticación opcional por API Key.
    """
    import weaviate
    try:
        from weaviate.auth import AuthApiKey
    except Exception:
        AuthApiKey = None
    auth = AuthApiKey(api_key=WEAVIATE_API_KEY) if (WEAVIATE_API_KEY and AuthApiKey) else None
    return weaviate.Client(url=WEAVIATE_URL, auth_client_secret=auth, timeout_config=(10, 120))

def initialize_weaviate_collection():
    """
    Crea la clase en Weaviate si no existe y muestra el conteo actual de objetos.
    """
    client = _weaviate_client()
    schema = client.schema.get()
    classes = [c['class'] for c in schema.get('classes', [])]
    if CLASS_NAME not in classes:
        client.schema.create_class(SCHEMA)
        print(f"[weaviate] Created class: {CLASS_NAME}")
    else:
        print(f"[weaviate] Class {CLASS_NAME} already exists")
    try:
        agg = client.query.aggregate(CLASS_NAME).with_meta_count().do()
        count = agg['data']['Aggregate'][CLASS_NAME][0]['meta']['count']
        print(f"[weaviate] Current docs: {count}")
    except Exception as e:
        print(f"[weaviate] Could not aggregate: {e}")
    return True

def _stable_uuid_for_pmid(pmid: str) -> str:
    """
    Genera un UUID v5 estable a partir del PMID (idempotencia).
    """
    ns = uuid.UUID("00000000-0000-0000-0000-00000000abcd")
    return str(uuid.uuid5(ns, pmid))

# =========================
# PubMed: descarga y parseo
# =========================
def fetch_pubmed_articles(**context):
    """
    Busca y descarga artículos de PubMed según un término de búsqueda.
    - Usa Entrez.esearch y Entrez.efetch con reintentos y backoff.
    - Devuelve una lista de diccionarios de artículos ya parseados.
    """
    from Bio import Entrez
    Entrez.email = ENTREZ_EMAIL
    if ENTREZ_API_KEY:
        Entrez.api_key = ENTREZ_API_KEY

    params = context.get('params', {}) or {}
    search_query = params.get('search_query', SEARCH_QUERY_DEFAULT)
    retmax = int(params.get('max_results', RETMAX_DEFAULT))
    print(f"[pubmed] Term: {search_query} | retmax={retmax} | email={ENTREZ_EMAIL}")

    ids: List[str] = []
    backoff = 1.0

    # Búsqueda con reintentos
    for attempt in range(5):
        try:
            with Entrez.esearch(db="pubmed", term=search_query, retmax=retmax, sort="relevance", retmode="xml") as h:
                res = Entrez.read(h)
            ids = res.get("IdList", [])
            break
        except Exception as e:
            print(f"[pubmed] esearch failed (attempt {attempt+1}): {e}")
            time.sleep(backoff)
            backoff = min(backoff * 2, 8.0)

    print(f"[pubmed] Found {len(ids)} ids")
    if not ids:
        return []

    articles: List[Dict[str, Any]] = []
    for i in range(0, len(ids), BATCH_SIZE_FETCH):
        batch = ids[i:i+BATCH_SIZE_FETCH]
        total_batches = (len(ids) - 1) // BATCH_SIZE_FETCH + 1
        print(f"[pubmed] Fetching batch {i//BATCH_SIZE_FETCH + 1}/{total_batches} ({len(batch)} ids)")
        for attempt in range(5):
            try:
                with Entrez.efetch(db="pubmed", id=batch, retmode="xml") as fh:
                    fetched = Entrez.read(fh)
                break
            except Exception as e:
                print(f"[pubmed] efetch failed (attempt {attempt+1}): {e}")
                time.sleep(0.5 * (attempt + 1))
        for art in fetched.get('PubmedArticle', []):
            parsed = parse_pubmed_article(art)
            if parsed:
                articles.append(parsed)
        time.sleep(0.35)  # respetar límites de NCBI

    print(f"[pubmed] Parsed {len(articles)} articles")
    return articles

def parse_pubmed_article(article) -> Dict:
    """
    Convierte la estructura XML de PubMed en un diccionario uniforme.
    - Omite artículos sin abstract (no útiles para embeddings).
    - Extrae autores, journal, fecha de publicación, MeSH, keywords, DOI,
      tipo de artículo y tamaño de muestra (heurístico).
    """
    try:
        medline = article.get('MedlineCitation', {})
        article_data = medline.get('Article', {})
        pmid = str(medline.get('PMID', ''))

        # Título
        title = article_data.get('ArticleTitle', '') or ''

        # Abstract
        abstract = ''
        if 'Abstract' in article_data:
            parts = article_data['Abstract'].get('AbstractText', [])
            segs = []
            for seg in parts:
                txt = str(seg)
                try:
                    label = getattr(seg, 'attributes', {}).get('Label')
                except Exception:
                    label = None
                segs.append(f"{label}: {txt}" if label else txt)
            abstract = ' '.join([s for s in segs if s]).strip()
        if not abstract:
            # Omitir ítems sin abstract
            return None

        # Autores
        authors = []
        for a in article_data.get('AuthorList', []):
            fn = a.get('ForeName'); ln = a.get('LastName')
            if fn and ln:
                authors.append(f"{fn} {ln}")

        # Journal
        journal = (article_data.get('Journal', {}) or {}).get('Title', '') or ''

        # Fecha de publicación (normalizada)
        pub_date = (article_data.get('Journal', {}).get('JournalIssue', {}) or {}).get('PubDate', {})
        year = str(pub_date.get('Year', '2025'))
        month = str(pub_date.get('Month', '01'))
        day = str(pub_date.get('Day', '01'))
        month_map = {'Jan':'01','Feb':'02','Mar':'03','Apr':'04','May':'05','Jun':'06','Jul':'07','Aug':'08','Sep':'09','Oct':'10','Nov':'11','Dec':'12'}
        month = month_map.get(month, month if month.isdigit() else '01')
        publication_date = f"{year}-{month.zfill(2)}-{day.zfill(2)}T00:00:00Z"

        # MeSH y Keywords
        mesh_terms = []
        for mh in medline.get('MeshHeadingList', []):
            dn = mh.get('DescriptorName')
            if dn:
                mesh_terms.append(str(dn))
        keywords = []
        for kwl in medline.get('KeywordList', []):
            keywords.extend([str(kw) for kw in kwl])

        # DOI
        doi = ''
        for eid in article_data.get('ELocationID', []):
            try:
                if getattr(eid, 'attributes', {}).get('EIdType') == 'doi':
                    doi = str(eid)
            except Exception:
                pass

        # Tipo de artículo / tipo de estudio
        pub_types = article_data.get('PublicationTypeList', [])
        article_type = str(pub_types[0]) if pub_types else 'Research Article'
        study_type = classify_study_type(article_type, abstract)

        # Tamaño de muestra (heurístico)
        import re
        sample_size = 0
        m = re.search(r'\bn\s*=\s*(\d+)\b', abstract.lower())
        if m:
            sample_size = int(m.group(1))

        # Hash de contenido para deduplicación
        content_hash = hashlib.md5(f"{pmid}|{title}|{abstract}".encode()).hexdigest()

        return {
            'pmid': pmid,
            'title': title,
            'abstract': abstract,
            'authors': authors,
            'journal': journal,
            'publication_date': publication_date,
            'mesh_terms': mesh_terms,
            'keywords': keywords,
            'doi': doi,
            'article_type': article_type,
            'citations_count': 0,
            'condition_focus': 'diabetes',
            'study_type': study_type,
            'sample_size': sample_size,
            'data_hash': content_hash,
            'embedding_model': EMBEDDING_MODEL,
            'ingestion_timestamp': datetime.utcnow().isoformat() + 'Z',
        }
    except Exception as e:
        print(f"[pubmed] Parse error: {e}")
        return None

def classify_study_type(article_type: str, abstract: str) -> str:
    """
    Clasifica de forma simple el tipo de estudio a partir del tipo de publicación y el abstract.
    """
    a = (article_type or '').lower()
    t = (abstract or '').lower()
    if 'clinical trial' in a or 'randomized' in t:
        return 'Clinical Trial'
    if 'meta-analysis' in a or 'meta-analysis' in t:
        return 'Meta-Analysis'
    if 'systematic review' in a or 'systematic review' in t:
        return 'Systematic Review'
    if 'case report' in a or 'case report' in t:
        return 'Case Report'
    if 'cohort' in t or 'prospective' in t:
        return 'Cohort Study'
    if 'cross-sectional' in t:
        return 'Cross-Sectional Study'
    return 'Observational Study'

# =========================
# Embeddings (por lotes)
# =========================
def generate_embeddings(**context):
    """
    Genera embeddings para los artículos usando SentenceTransformers.
    - Concadena título, abstract, keywords y MeSH para el texto a vectorizar.
    - Emplea lotes y semilla fija para reproducibilidad.
    """
    from sentence_transformers import SentenceTransformer
    import numpy as np

    ti = context['task_instance']
    articles = ti.xcom_pull(task_ids='fetch_pubmed_articles') or []
    if not articles:
        print("[embed] No articles to embed")
        return []

    random.seed(SEED)
    np.random.seed(SEED)

    print(f"[embed] Embedding {len(articles)} docs | model={EMBEDDING_MODEL}")
    try:
        model = SentenceTransformer(EMBEDDING_MODEL)
    except Exception as e:
        print(f"[embed] Failed to load {EMBEDDING_MODEL}: {e} | using fallback all-MiniLM-L6-v2")
        model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")

    texts = []
    for a in articles:
        t = f"{a['title']} {a['abstract']}"
        if a.get('keywords'):
            t += " " + " ".join(a['keywords'])
        if a.get('mesh_terms'):
            t += " " + " ".join(a['mesh_terms'])
        texts.append(t[:4000])  # seguridad por longitud

    # Encode por lotes
    vecs = model.encode(
        texts,
        batch_size=BATCH_SIZE_EMB,
        show_progress_bar=True,
        convert_to_numpy=True,
        normalize_embeddings=False
    )

    out = []
    for a, v in zip(articles, vecs):
        tmp = dict(a)
        tmp['embedding'] = v.tolist()
        out.append(tmp)

    print(f"[embed] Embedded: {len(out)}")
    return out

# =========================
# Carga en Weaviate (por lotes + upsert)
# =========================
def load_to_weaviate(**context):
    """
    Carga los artículos con embeddings en Weaviate.
    - Consulta PMIDs existentes para acelerar upsert.
    - Reemplaza objetos existentes y añade nuevos en batch.
    - Guarda métricas en Variable.set('last_medical_ingestion').
    """
    import weaviate

    ti = context['task_instance']
    articles = ti.xcom_pull(task_ids='generate_embeddings') or []
    if not articles:
        print("[load] No articles to load")
        return {'loaded': 0, 'replaced': 0, 'skipped': 0, 'failed': 0}

    client = _weaviate_client()
    stats = {'loaded': 0, 'replaced': 0, 'skipped': 0, 'failed': 0}

    # Conjunto de PMIDs existentes para decisiones rápidas
    existing_pmids = set()
    try:
        got = client.query.get(CLASS_NAME, ['pmid']).with_limit(10000).do()
        existing_pmids = {x['pmid'] for x in got.get('data', {}).get('Get', {}).get(CLASS_NAME, []) if x.get('pmid')}
        print(f"[load] Existing pmids: {len(existing_pmids)}")
    except Exception as e:
        print(f"[load] Could not list existing pmids: {e}")

    # Configuración de batch
    client.batch.configure(batch_size=BATCH_SIZE_WEAV, dynamic=True, timeout_retries=3)

    with client.batch as batch:
        for i, art in enumerate(articles, 1):
            try:
                pmid = art.get('pmid')
                if not pmid:
                    stats['skipped'] += 1
                    continue

                obj_uuid = _stable_uuid_for_pmid(pmid)
                vec = art.pop('embedding')

                # Upsert: replace si existe, add si no
                if pmid in existing_pmids:
                    client.data_object.replace(
                        data_object=art,
                        class_name=CLASS_NAME,
                        uuid=obj_uuid,
                        vector=vec
                    )
                    stats['replaced'] += 1
                else:
                    batch.add_data_object(
                        data_object=art,
                        class_name=CLASS_NAME,
                        uuid=obj_uuid,
                        vector=vec
                    )
                    stats['loaded'] += 1

                if (i % 200) == 0:
                    print(f"[load] Processed {i}/{len(articles)}")

            except Exception as e:
                stats['failed'] += 1
                print(f"[load] Error loading PMID {art.get('pmid')}: {e}")

    print(f"[load] COMPLETE | loaded={stats['loaded']}, replaced={stats['replaced']}, skipped={stats['skipped']}, failed={stats['failed']}")
    Variable.set("last_medical_ingestion", json.dumps({
        'timestamp': datetime.utcnow().isoformat() + 'Z',
        'stats': stats,
        'total_processed': len(articles),
        'batch_size': BATCH_SIZE_WEAV
    }))
    return stats

# =========================
# Definición del DAG
# =========================
with DAG(
    'medical_research_ingestion_v2',
    default_args=default_args,
    description='Ingesta de investigación médica desde PubMed hacia Weaviate (por lotes, idempotente)',
    schedule=None,  # disparo manual
    catchup=False,
    params={
        'search_query': SEARCH_QUERY_DEFAULT,
        'max_results': RETMAX_DEFAULT
    },
    tags=['healthcare', 'pubmed', 'research', 'ingestion', 'weaviate'],
    max_active_runs=1,
) as dag:

    setup_deps = PythonOperator(
        task_id='setup_dependencies',
        python_callable=setup_dependencies,
    )

    init_weaviate = PythonOperator(
        task_id='initialize_weaviate',
        python_callable=initialize_weaviate_collection,
    )

    fetch_articles = PythonOperator(
        task_id='fetch_pubmed_articles',
        python_callable=fetch_pubmed_articles,
    )

    create_embeddings = PythonOperator(
        task_id='generate_embeddings',
        python_callable=generate_embeddings,
    )

    load_data = PythonOperator(
        task_id='load_to_weaviate',
        python_callable=load_to_weaviate,
    )

    setup_deps >> init_weaviate >> fetch_articles >> create_embeddings >> load_data
