# -*- coding: utf-8 -*-
"""
DAG de Airflow: Validación y Búsqueda de Similitud en 'DiabetesPatients' (Weaviate)
===================================================================================

Propósito
---------
Validar la colección 'DiabetesPatients' (esquema BYOV) y ejecutar búsquedas de
pacientes similares para evaluar la calidad de los datos y el comportamiento de
las consultas vectoriales/filtradas.

Fases del pipeline
------------------
1) install_packages: instala dependencias en tiempo de ejecución (en prod, mejor en la imagen).
2) validate_collection: verifica existencia y conteo de la colección y muestra una pequeña muestra.
3) cohort_stats: carga hasta VAR_SAMPLE_LIMIT objetos y calcula métricas de cohorte y correlaciones.
4) similar_patients_searches: realiza búsquedas de similitud (nearObject) con y sin filtros.
5) validation_report: consolida resultados y emite recomendaciones operativas.

Salidas y Variables de Airflow
------------------------------
- diabetes_health: {'total': <int>, 'class': <str>}
- diabetes_stats: métricas de cohorte (promedios, distribuciones, correlaciones).
- diabetes_similarity_examples: ancla y ejemplos de pacientes similares/cohorte filtrada.
- diabetes_validation_report: reporte consolidado con estado y recomendaciones.

Configuración (ENV + Variables)
-------------------------------
ENV:
  - WEAVIATE_URL, WEAVIATE_API_KEY (opcional)
Variables (UI de Airflow):
  - diab_class_name (por defecto: DiabetesPatients)
  - diab_top_k (top K para búsquedas)
  - diab_sample_limit (límite para cargar muestra en estadísticas)
  - diab_validation_seed (semilla)
  - diab_min_hba1c_uncontrolled (umbral HbA1c para "no controlado")
  - diab_min_bmi_obese (umbral BMI para obesidad)
  - diab_min_age_filter / diab_max_age_filter (rango etario)
"""

import os
import sys
import json
import random
import subprocess
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.models import Variable

# =========================
# Config (ENV + Variables)
# =========================
WEAVIATE_URL = os.getenv("WEAVIATE_URL", "http://weaviate.weaviate.svc.cluster.local:8080")
WEAVIATE_API_KEY = os.getenv("WEAVIATE_API_KEY")  # opcional

VAR_CLASS = Variable.get("diab_class_name", default_var="DiabetesPatients")
VAR_TOP_K = int(Variable.get("diab_top_k", default_var="5"))
VAR_SAMPLE_LIMIT = int(Variable.get("diab_sample_limit", default_var="10000"))  # para stats
VAR_SEED = int(Variable.get("diab_validation_seed", default_var="2025"))

# Filtros y umbrales por defecto
VAR_MIN_HBA1C_UNCONTROLLED = float(Variable.get("diab_min_hba1c_uncontrolled", default_var="9.0"))
VAR_MIN_BMI_OBESE = float(Variable.get("diab_min_bmi_obese", default_var="30"))
VAR_MIN_AGE = int(Variable.get("diab_min_age_filter", default_var="18"))
VAR_MAX_AGE = int(Variable.get("diab_max_age_filter", default_var="95"))

default_args = {
    'owner': 'healthcare-team',
    'depends_on_past': False,
    'start_date': datetime(2025, 1, 1),
    'email_on_failure': False,
    'email_on_retry': False,
    'retries': 1,
    'retry_delay': timedelta(minutes=2),
}

# =========================
# Utils
# =========================
def install_packages():
    """
    Instala dependencias en tiempo de ejecución.
    Recomendación: en producción, incluirlas en la imagen del worker.
    """
    packages = [
        'weaviate-client>=3.25.0',
        'pandas',
        'numpy',
    ]
    for p in packages:
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "--quiet", p])
            print(f"[deps] Installed {p}")
        except Exception as e:
            print(f"[deps] Failed to install {p}: {e}")

def _weaviate_client():
    """
    Devuelve un cliente de Weaviate con autenticación opcional por API Key.
    """
    import weaviate
    try:
        from weaviate.auth import AuthApiKey
    except Exception:
        AuthApiKey = None
    auth = None
    if WEAVIATE_API_KEY and AuthApiKey:
        auth = AuthApiKey(api_key=WEAVIATE_API_KEY)
    client = weaviate.Client(
        url=WEAVIATE_URL,
        auth_client_secret=auth,
        timeout_config=(10, 120),
    )
    return client

def _print_title(t: str):
    """
    Imprime un encabezado simple sin iconos.
    """
    print("\n" + "=" * len(t))
    print(t)
    print("=" * len(t))

# =========================
# Tasks
# =========================
def validate_collection():
    """
    Comprueba la existencia de la colección, su conteo de objetos y muestra
    una pequeña muestra con campos clave. Guarda resultados en 'diabetes_health'.
    """
    import traceback
    client = _weaviate_client()
    class_name = VAR_CLASS

    _print_title("DIABETES PATIENTS COLLECTION HEALTH CHECK")

    try:
        schema = client.schema.get()
        exists = any(c['class'] == class_name for c in schema.get('classes', []))
        if not exists:
            raise ValueError(f"Collection '{class_name}' not found. Ejecuta primero la ingesta.")

        print(f"[health] Collection '{class_name}' exists")

        agg = client.query.aggregate(class_name).with_meta_count().do()
        total = agg['data']['Aggregate'][class_name][0]['meta']['count']
        print(f"[health] Total objects: {total}")
        if total == 0:
            raise ValueError("Collection is empty.")

        # Muestra de objetos con campos clave y el id
        fields = [
            'patient_id','age','gender','diabetes_type','hba1c_current','bmi',
            'glucose_fasting','egfr','creatinine','clinical_summary'
        ]
        sample = client.query.get(class_name, fields)\
            .with_limit(5)\
            .with_additional(['id'])\
            .do()
        docs = sample['data']['Get'].get(class_name, [])
        print("\n[health] Sample (5):")
        for i, d in enumerate(docs, 1):
            pid = d.get('patient_id')
            _id = d.get('_additional', {}).get('id')
            age = d.get('age'); g = d.get('gender'); typ = d.get('diabetes_type')
            hba1c = d.get('hba1c_current'); bmi = d.get('bmi')
            print(f"  {i}. {_id} | {pid} | {age} {g} {typ} | HbA1c {hba1c} | BMI {bmi}")

        Variable.set("diabetes_health", json.dumps({'total': total, 'class': class_name}))
        return {'total': total, 'class': class_name}

    except Exception as e:
        print("[health] Error:", e)
        traceback.print_exc()
        raise

def cohort_stats():
    """
    Carga hasta VAR_SAMPLE_LIMIT objetos y calcula métricas de cohorte:
    - Distribuciones por tipo y género, promedios (edad, HbA1c, BMI, eGFR, etc.)
    - Porcentaje con HbA1c < 7%
    - P95 de ACR
    - Correlaciones HbA1c↔Glucosa en ayunas y Creatinina↔eGFR
    Guarda resultados en 'diabetes_stats'.
    """
    import pandas as pd
    client = _weaviate_client()
    class_name = VAR_CLASS
    limit = VAR_SAMPLE_LIMIT

    _print_title("COHORT STATS")

    fields = [
        'patient_id','age','gender','diabetes_type','years_since_diagnosis',
        'hba1c_current','hba1c_baseline','bmi','glucose_fasting','glucose_random',
        'blood_pressure_systolic','blood_pressure_diastolic','egfr','creatinine',
        'ldl_cholesterol','hdl_cholesterol','triglycerides','albumin_creatinine_ratio',
        'cardiovascular_risk_score','kidney_disease_risk','retinopathy_risk','neuropathy_risk',
        'hospitalizations_past_year','emergency_visits_past_year'
    ]

    res = client.query.get(class_name, fields).with_limit(limit).with_additional(['id']).do()
    items = res['data']['Get'].get(class_name, [])
    if not items:
        raise ValueError("No items returned for stats.")

    df = pd.DataFrame(items)
    if '_additional' in df.columns:
        df['_id'] = df['_additional'].apply(lambda x: (x or {}).get('id'))
        df = df.drop(columns=['_additional'])

    n = len(df)
    print(f"[stats] Loaded {n} objects for stats (limit={limit})")

    stats = {
        'count': int(n),
        'type_distribution': df['diabetes_type'].value_counts(dropna=False).to_dict(),
        'gender_distribution': df['gender'].value_counts(dropna=False).to_dict(),
        'avg_age': float(df['age'].mean()),
        'avg_hba1c': float(df['hba1c_current'].mean()),
        'pct_hba1c_under_7': float((df['hba1c_current'] < 7.0).mean() * 100.0),
        'avg_bmi': float(df['bmi'].mean()),
        'p95_acr': float(df['albumin_creatinine_ratio'].quantile(0.95)),
        'avg_egfr': float(df['egfr'].mean()),
        'avg_creatinine': float(df['creatinine'].mean()),
        'avg_hosp_past_year': float(df['hospitalizations_past_year'].mean()),
    }

    corr_hba1c_glu = float(df[['hba1c_current','glucose_fasting']].corr().iloc[0,1])
    corr_crea_egfr = float
