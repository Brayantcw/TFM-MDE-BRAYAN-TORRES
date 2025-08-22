"""
Diabetes Patients Validation & Similarity DAG (Weaviate)
Valida la colección 'DiabetesPatients' (esquema BYOV) y ejecuta búsquedas de pacientes similares.
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
    """Instala dependencias (idealmente inclúyelas en la imagen del worker)."""
    packages = [
        'weaviate-client>=3.25.0',
        'pandas',
        'numpy',
    ]
    for p in packages:
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "--quiet", p])
            print(f"✅ Installed {p}")
        except Exception as e:
            print(f"⚠️ Failed to install {p}: {e}")

def _weaviate_client():
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
    print("\n" + "=" * len(t))
    print(t)
    print("=" * len(t))

# =========================
# Tasks
# =========================
def validate_collection():
    """Comprueba existencia, cuenta y muestra de la colección."""
    import traceback
    client = _weaviate_client()
    class_name = VAR_CLASS

    _print_title("🏥 DIABETES PATIENTS COLLECTION HEALTH CHECK")

    try:
        schema = client.schema.get()
        exists = any(c['class'] == class_name for c in schema.get('classes', []))
        if not exists:
            raise ValueError(f"Collection '{class_name}' not found. Ejecuta primero la ingesta.")

        print(f"✅ Collection '{class_name}' exists")

        agg = client.query.aggregate(class_name).with_meta_count().do()
        total = agg['data']['Aggregate'][class_name][0]['meta']['count']
        print(f"📊 Total objects: {total}")
        if total == 0:
            raise ValueError("Collection is empty.")

        # Pequeña muestra de objetos con campos clave y el id
        fields = [
            'patient_id','age','gender','diabetes_type','hba1c_current','bmi',
            'glucose_fasting','egfr','creatinine','clinical_summary'
        ]
        sample = client.query.get(class_name, fields)\
            .with_limit(5)\
            .with_additional(['id'])\
            .do()
        docs = sample['data']['Get'].get(class_name, [])
        print("\n📚 Sample (5):")
        for i, d in enumerate(docs, 1):
            pid = d.get('patient_id')
            _id = d.get('_additional', {}).get('id')
            age = d.get('age'); g = d.get('gender'); typ = d.get('diabetes_type')
            hba1c = d.get('hba1c_current'); bmi = d.get('bmi')
            print(f"  {i}. {_id} | {pid} | {age} {g} {typ} | HbA1c {hba1c} | BMI {bmi}")

        Variable.set("diabetes_health", json.dumps({'total': total, 'class': class_name}))
        return {'total': total, 'class': class_name}

    except Exception as e:
        print("❌ Error:", e)
        traceback.print_exc()
        raise

def cohort_stats():
    """Descarga hasta VAR_SAMPLE_LIMIT objetos y calcula métricas de cohorte."""
    import pandas as pd
    client = _weaviate_client()
    class_name = VAR_CLASS
    limit = VAR_SAMPLE_LIMIT

    _print_title("📈 COHORT STATS")

    # Paginar si fuese necesario (aquí usamos limit "grande" para datasets de ~500–10k)
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
    # Limpiar _additional
    if '_additional' in df.columns:
        df['_id'] = df['_additional'].apply(lambda x: (x or {}).get('id'))
        df = df.drop(columns=['_additional'])

    n = len(df)
    print(f"📦 Loaded {n} objects for stats (limit={limit})")

    # Métricas clave
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

    # Correlaciones de coherencia clínica
    corr_hba1c_glu = float(df[['hba1c_current','glucose_fasting']].corr().iloc[0,1])
    corr_crea_egfr = float(df[['creatinine','egfr']].corr().iloc[0,1])
    # Comparar BMI entre T2 y T1
    try:
        bmi_t2 = float(df[df['diabetes_type']=='Type 2']['bmi'].mean())
        bmi_t1 = float(df[df['diabetes_type']=='Type 1']['bmi'].mean())
    except Exception:
        bmi_t2, bmi_t1 = float('nan'), float('nan')

    stats['corr_hba1c_glucose_fasting'] = corr_hba1c_glu
    stats['corr_creatinine_egfr'] = corr_crea_egfr
    stats['avg_bmi_type2'] = bmi_t2
    stats['avg_bmi_type1'] = bmi_t1

    print("\n🔎 Key stats:")
    for k,v in stats.items():
        if isinstance(v, float):
            print(f"  {k:30}: {v:.3f}")
        else:
            print(f"  {k:30}: {v}")

    Variable.set("diabetes_stats", json.dumps(stats))
    return stats

def similar_patients_searches():
    """Ejecuta consultas de similitud: nearObject + filtros clínicos."""
    import pandas as pd
    random.seed(VAR_SEED)
    client = _weaviate_client()
    class_name = VAR_CLASS
    k = VAR_TOP_K

    _print_title("🔍 SIMILAR PATIENTS SEARCHES")

    # 1) Encontrar un ancla: T2DM no controlado (HbA1c >= threshold) y obeso (BMI >= umbral)
    fields = ['patient_id','diabetes_type','hba1c_current','bmi','age','gender']
    res = client.query.get(class_name, fields)\
        .with_limit(VAR_SAMPLE_LIMIT)\
        .with_additional(['id'])\
        .do()
    items = res['data']['Get'].get(class_name, [])
    if not items:
        raise ValueError("No patients to search.")

    # Filtrar candidatos
    uncontrolled = [
        x for x in items
        if (x.get('diabetes_type') == 'Type 2'
            and (x.get('hba1c_current') or 0) >= VAR_MIN_HBA1C_UNCONTROLLED
            and (x.get('bmi') or 0) >= VAR_MIN_BMI_OBESE
            and (x.get('age') or 0) >= VAR_MIN_AGE
            and (x.get('age') or 0) <= VAR_MAX_AGE)
    ]
    anchor = random.choice(uncontrolled) if uncontrolled else random.choice(items)
    anchor_id = anchor.get('_additional', {}).get('id')
    print(f"🎯 Anchor patient (nearObject): id={anchor_id}, pid={anchor.get('patient_id')}, "
          f"type={anchor.get('diabetes_type')}, HbA1c={anchor.get('hba1c_current')}, BMI={anchor.get('bmi')}")

    # 2) nearObject básico (excluir el propio ancla con where patient_id !=)
    where_filter = {
        "path": ["patient_id"],
        "operator": "NotEqual",
        "valueString": anchor.get('patient_id')
    }
    fields_detail = [
        'patient_id','age','gender','diabetes_type','hba1c_current','bmi',
        'glucose_fasting','egfr','cardiovascular_risk_score','kidney_disease_risk'
    ]
    res_knn = client.query.get(class_name, fields_detail)\
        .with_near_object({"id": anchor_id})\
        .with_where(where_filter)\
        .with_limit(k)\
        .with_additional(['certainty','distance','id'])\
        .do()
    hits = res_knn['data']['Get'].get(class_name, [])
    print(f"   ✅ Found {len(hits)} similar patients (K={k})")
    for i, h in enumerate(hits, 1):
        add = h.get('_additional', {})
        cert = add.get('certainty')
        dist = add.get('distance')
        print(f"   {i}. {h.get('patient_id')} | {h.get('diabetes_type')} | "
              f"HbA1c {h.get('hba1c_current')} | BMI {h.get('bmi')} | "
              f"cert={cert:.3f} dist={dist:.3f}" if cert is not None and dist is not None else
              f"   {i}. {h.get('patient_id')} | score info N/A")

    # 3) nearObject + filtros clínicos (ej: misma diabetes_type, mismo sexo)
    where_filter2 = {
        "operator":"And",
        "operands":[
            {"path":["diabetes_type"],"operator":"Equal","valueString": anchor.get('diabetes_type', 'Type 2')},
            {"path":["gender"],"operator":"Equal","valueString": anchor.get('gender','Male')}
        ]
    }
    res_knn_f = client.query.get(class_name, fields_detail)\
        .with_near_object({"id": anchor_id})\
        .with_where(where_filter2)\
        .with_limit(k)\
        .with_additional(['certainty','distance','id'])\
        .do()
    hits2 = res_knn_f['data']['Get'].get(class_name, [])
    print(f"\n   ✅ Found {len(hits2)} similar patients with same type & gender:")
    for i, h in enumerate(hits2, 1):
        add = h.get('_additional', {})
        cert = add.get('certainty')
        dist = add.get('distance')
        print(f"   {i}. {h.get('patient_id')} | {h.get('gender')} | {h.get('diabetes_type')} | "
              f"HbA1c {h.get('hba1c_current')} | BMI {h.get('bmi')} | "
              f"cert={cert:.3f} dist={dist:.3f}" if cert is not None and dist is not None else
              f"   {i}. {h.get('patient_id')}")

    # 4) Búsqueda por criterios sin vector (ej.: T2DM, HbA1c>=9, BMI>=30) para revisar cohorte problemática
    where_filter3 = {
        "operator":"And",
        "operands":[
            {"path":["diabetes_type"],"operator":"Equal","valueString":"Type 2"},
            {"path":["hba1c_current"],"operator":"GreaterThanEqual","valueNumber": VAR_MIN_HBA1C_UNCONTROLLED},
            {"path":["bmi"],"operator":"GreaterThanEqual","valueNumber": VAR_MIN_BMI_OBESE},
        ]
    }
    res_filter = client.query.get(class_name, fields_detail)\
        .with_where(where_filter3)\
        .with_limit(min(k, 10))\
        .with_additional(['id'])\
        .do()
    cohort = res_filter['data']['Get'].get(class_name, [])
    print(f"\n   🔬 Cohort (T2DM, HbA1c>={VAR_MIN_HBA1C_UNCONTROLLED}, BMI>={VAR_MIN_BMI_OBESE}) → {len(cohort)} muestras")
    for i, c in enumerate(cohort[:k], 1):
        print(f"   {i}. {c.get('patient_id')} | HbA1c {c.get('hba1c_current')} | BMI {c.get('bmi')}")

    # Guardar ejemplos
    out = {
        'anchor': {
            'id': anchor_id,
            'patient_id': anchor.get('patient_id'),
            'gender': anchor.get('gender'),
            'diabetes_type': anchor.get('diabetes_type'),
            'hba1c_current': anchor.get('hba1c_current'),
            'bmi': anchor.get('bmi'),
        },
        'similar_basic': hits,
        'similar_same_type_gender': hits2,
        'cohort_uncontrolled_obese': cohort[:k]
    }
    Variable.set("diabetes_similarity_examples", json.dumps(out))
    return {'anchor_id': anchor_id, 'k': k, 'basic': len(hits), 'filtered': len(hits2), 'cohort': len(cohort)}

def validation_report():
    """Consolida health + stats + searches y emite recomendaciones."""
    _print_title("📄 DIABETES VALIDATION REPORT")
    try:
        health = json.loads(Variable.get("diabetes_health", "{}"))
        stats = json.loads(Variable.get("diabetes_stats", "{}"))
        sims = json.loads(Variable.get("diabetes_similarity_examples", "{}"))

        total = int(health.get('total', 0))
        avg_hba1c = float(stats.get('avg_hba1c', 0.0))
        pct_under7 = float(stats.get('pct_hba1c_under_7', 0.0))
        corr_hg = float(stats.get('corr_hba1c_glucose_fasting', 0.0))
        corr_ce = float(stats.get('corr_creatinine_egfr', 0.0))
        bmi_t2 = float(stats.get('avg_bmi_type2', 0.0))
        bmi_t1 = float(stats.get('avg_bmi_type1', 0.0))

        recs = []
        status = "OPERATIONAL"

        # Checks simples de coherencia clínica
        if corr_hg < 0.45:
            recs.append("La correlación HbA1c↔Glucosa en ayunas es baja (<0.45). Revisa generación/ruido.")
            status = "WARNINGS"
        if corr_ce > -0.3:  # debería ser negativa clara
            recs.append("La correlación Creatinina↔eGFR no es claramente negativa. Revisar fórmula/ruido.")
            status = "WARNINGS"
        if not (bmi_t2 > bmi_t1):
            recs.append("El BMI medio en T2DM no es mayor que en T1DM. Ajustar distribución de BMI.")
            status = "WARNINGS"
        if pct_under7 < 20 or pct_under7 > 70:
            recs.append("Proporción con HbA1c<7% fuera de rango típico (20–70%). Ajusta control glucémico.")
            status = "WARNINGS"
        if total < 200:
            recs.append("Pocos pacientes (<200). Incrementa la cohorte para mayor robustez.")
            status = "NEEDS_MORE_DATA"

        report = {
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'class': VAR_CLASS,
            'total': total,
            'metrics': stats,
            'similarity_examples_summary': {
                'anchor': sims.get('anchor', {}),
                'counts': {
                    'basic': len(sims.get('similar_basic', [])),
                    'filtered': len(sims.get('similar_same_type_gender', [])),
                    'cohort': len(sims.get('cohort_uncontrolled_obese', []))
                }
            },
            'recommendations': recs,
            'overall_status': status
        }

        print("\n📊 SUMMARY")
        print(f"  Total patients: {total}")
        print(f"  Avg HbA1c: {avg_hba1c:.2f} | %<7%: {pct_under7:.1f}%")
        print(f"  Corr(HbA1c, GluFast): {corr_hg:.2f} | Corr(Crea, eGFR): {corr_ce:.2f}")
        print(f"  BMI mean (T2 vs T1): {bmi_t2:.1f} vs {bmi_t1:.1f}")
        if recs:
            print("\n💡 Recommendations:")
            for r in recs:
                print(f"   • {r}")

        Variable.set("diabetes_validation_report", json.dumps(report))
        print("\n✅ Report stored in Variable 'diabetes_validation_report'")
        return report

    except Exception as e:
        print(f"❌ Error building report: {e}")
        raise

# =========================
# DAG
# =========================
with DAG(
    dag_id='synthetic_patient_data_validation_v1',
    default_args=default_args,
    description='Validate DiabetesPatients collection, compute stats, and run similarity searches',
    schedule=None,
    catchup=False,
    tags=['healthcare','validation','weaviate','patients','similarity'],
    max_active_runs=1,
) as dag:

    task_install = PythonOperator(
        task_id='install_packages',
        python_callable=install_packages,
    )

    task_health = PythonOperator(
        task_id='validate_collection',
        python_callable=validate_collection,
    )

    task_stats = PythonOperator(
        task_id='cohort_stats',
        python_callable=cohort_stats,
    )

    task_similarity = PythonOperator(
        task_id='similar_patients_searches',
        python_callable=similar_patients_searches,
    )

    task_report = PythonOperator(
        task_id='validation_report',
        python_callable=validation_report,
    )

    task_install >> task_health >> task_stats >> task_similarity >> task_report
