# -*- coding: utf-8 -*-
"""
DAG de Airflow: Ingesta de Pacientes Sintéticos (Diabetes) con Embeddings
=========================================================================
Propósito
---------
Generar registros sintéticos de pacientes con diabetes, crear embeddings
a partir de un resumen clínico y cargarlos en una colección de Weaviate.
El flujo es idempotente y por lotes.

Fases del pipeline
------------------
1) setup_dependencies: instala/importa dependencias (en prod, preferible en la imagen).
2) initialize_patient_collection: crea el esquema/clase en Weaviate si no existe y muestra conteo.
3) generate_synthetic_patients: genera pacientes sintéticos reproducibles (semilla fija).
4) generate_patient_embeddings: vectoriza el resumen clínico con SentenceTransformers.
5) load_to_weaviate: carga/upsert en Weaviate usando UUID v5 estable por patient_id.

Idempotencia
------------
Cada paciente se identifica con un UUID v5 estable derivado del patient_id.
Si el objeto ya existe, se reemplaza (upsert) en lugar de duplicarse.

Configuración
-------------
Variables de entorno:
  - WEAVIATE_URL, WEAVIATE_API_KEY (opcional), WEAVIATE_TLS (si usas HTTPS verificado)
Variables de Airflow (UI):
  - num_patients (número de pacientes a generar)
  - weaviate_batch_size (tamaño de lote de carga)
  - embedding_model (modelo de embeddings para los resúmenes)
  - synthetic_seed (semilla para reproducibilidad)

Notas operativas
----------------
- En producción, hornear dependencias en la imagen de los workers.
- El pipeline imprime métricas básicas (HbA1c promedio, % controlados, % con complicaciones).
"""

import subprocess
import sys
import os
import json
import hashlib
import uuid
import random
from typing import List, Dict, Any
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.models import Variable

# ---------------------------
# Dependencias en tiempo de ejecución (fallback)
# ---------------------------
def install_packages():
    """
    Instala paquetes requeridos en tiempo de ejecución.
    En producción se recomienda incluirlos en la imagen del worker.
    """
    packages = ['sentence-transformers>=2.2.3', 'numpy', 'pandas', 'weaviate-client>=3.25.0']
    for package in packages:
        try:
            subprocess.check_call([sys.executable, '-m', 'pip', 'install', '--quiet', package])
            print(f"[deps] Installed {package}")
        except Exception as e:
            print(f"[deps] Failed to install {package}: {e}")

# ---------------------------
# Configuración (ENV + Variables de Airflow)
# ---------------------------
WEAVIATE_URL = os.getenv("WEAVIATE_URL", "http://weaviate.weaviate.svc.cluster.local:8080")
WEAVIATE_API_KEY = os.getenv("WEAVIATE_API_KEY")  # opcional
WEAVIATE_TLS = os.getenv("WEAVIATE_TLS", "false").lower() == "true"  # si usas https con verificación

VAR_PATIENTS = int(Variable.get("num_patients", default_var="500"))
VAR_BATCH_SIZE = int(Variable.get("weaviate_batch_size", default_var="200"))
VAR_EMB_MODEL = Variable.get("embedding_model", default_var="pritamdeka/S-PubMedBert-MS-MARCO")
VAR_SEED = int(Variable.get("synthetic_seed", default_var="42"))

# ---------------------------
# Esquema de Weaviate
# ---------------------------
PATIENT_CLASS = "DiabetesPatients"
PATIENT_SCHEMA = {
    "class": PATIENT_CLASS,
    "description": "Synthetic diabetes patient records for similarity matching",
    "vectorizer": "none",
    "properties": [
        {"name": "patient_id", "dataType": ["text"], "description": "Unique patient identifier"},
        {"name": "age", "dataType": ["int"]},
        {"name": "gender", "dataType": ["text"]},
        {"name": "diabetes_type", "dataType": ["text"]},
        {"name": "years_since_diagnosis", "dataType": ["number"]},

        {"name": "hba1c_current", "dataType": ["number"]},
        {"name": "hba1c_baseline", "dataType": ["number"]},
        {"name": "glucose_fasting", "dataType": ["number"]},
        {"name": "glucose_random", "dataType": ["number"]},
        {"name": "bmi", "dataType": ["number"]},
        {"name": "blood_pressure_systolic", "dataType": ["int"]},
        {"name": "blood_pressure_diastolic", "dataType": ["int"]},

        {"name": "creatinine", "dataType": ["number"]},
        {"name": "egfr", "dataType": ["number"]},
        {"name": "ldl_cholesterol", "dataType": ["number"]},
        {"name": "hdl_cholesterol", "dataType": ["number"]},
        {"name": "triglycerides", "dataType": ["number"]},
        {"name": "albumin_creatinine_ratio", "dataType": ["number"]},

        {"name": "symptoms", "dataType": ["text[]"]},
        {"name": "complications", "dataType": ["text[]"]},
        {"name": "comorbidities", "dataType": ["text[]"]},

        {"name": "medications", "dataType": ["text[]"]},
        {"name": "medication_adherence", "dataType": ["number"]},

        {"name": "smoking_status", "dataType": ["text"]},
        {"name": "alcohol_use", "dataType": ["text"]},
        {"name": "exercise_weekly_hours", "dataType": ["number"]},
        {"name": "diet_quality_score", "dataType": ["int"]},

        {"name": "cardiovascular_risk_score", "dataType": ["number"]},
        {"name": "kidney_disease_risk", "dataType": ["number"]},
        {"name": "retinopathy_risk", "dataType": ["number"]},
        {"name": "neuropathy_risk", "dataType": ["number"]},

        {"name": "treatment_response", "dataType": ["text"]},
        {"name": "hba1c_change", "dataType": ["number"]},
        {"name": "weight_change", "dataType": ["number"]},

        {"name": "hospitalizations_past_year", "dataType": ["int"]},
        {"name": "emergency_visits_past_year", "dataType": ["int"]},

        {"name": "insurance_type", "dataType": ["text"]},
        {"name": "socioeconomic_score", "dataType": ["int"]},

        {"name": "clinical_summary", "dataType": ["text"]},
        {"name": "last_updated", "dataType": ["date"]},
        {"name": "data_quality_score", "dataType": ["number"]},
    ],
}

# ---------------------------
# Parámetros por defecto del DAG
# ---------------------------
default_args = {
    'owner': 'healthcare-team',
    'depends_on_past': False,
    'start_date': datetime(2025, 1, 1),
    'email_on_failure': False,
    'email_on_retry': False,
    'retries': 2,
    'retry_delay': timedelta(minutes=5),
}

# ---------------------------
# Helpers
# ---------------------------
def setup_dependencies():
    """
    Instala e importa dependencias en tiempo de ejecución.
    Devuelve True si los imports se realizaron correctamente.
    """
    install_packages()
    global np, SentenceTransformer, weaviate, AuthApiKey
    import numpy as np
    from sentence_transformers import SentenceTransformer
    import weaviate
    try:
        from weaviate.auth import AuthApiKey
    except Exception:
        AuthApiKey = None
    print("[deps] Runtime dependencies ready")
    return True

def weaviate_client():
    """
    Devuelve un cliente de Weaviate con autenticación opcional por API Key.
    Para TLS con certificados propios, usar WEAVIATE_TLS=true y URL https://
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
        additional_headers={},
        timeout_config=(10, 120),  # connect, read
    )
    return client

def initialize_patient_collection():
    """
    Crea la clase en Weaviate si no existe y muestra el conteo actual de objetos.
    """
    client = weaviate_client()
    schema = client.schema.get()
    existing = [c['class'] for c in schema.get('classes', [])]
    if PATIENT_CLASS not in existing:
        client.schema.create_class(PATIENT_SCHEMA)
        print(f"[weaviate] Created class: {PATIENT_CLASS}")
    else:
        print(f"[weaviate] Class {PATIENT_CLASS} already exists")

    # Conteo rápido
    try:
        agg = client.query.aggregate(PATIENT_CLASS).with_meta_count().do()
        count = agg['data']['Aggregate'][PATIENT_CLASS][0]['meta']['count']
        print(f"[weaviate] Current objects: {count}")
    except Exception as e:
        print(f"[weaviate] Could not aggregate count: {e}")
    return True

def set_seeds(seed: int):
    """Fija las semillas de random y numpy para reproducibilidad."""
    import numpy as np
    random.seed(seed)
    np.random.seed(seed)

def calculate_cv_risk(age, gender, bp_systolic, ldl, hdl, smoking, diabetes):
    """
    Calcula un riesgo cardiovascular simplificado (0..1) a partir de factores básicos.
    Este cálculo es heurístico y solo con fines de simulación.
    """
    risk = 0.1
    risk += max(0, (age - 40) * 0.01)
    if gender == "Male":
        risk += 0.05
    if bp_systolic > 140:
        risk += 0.1
    elif bp_systolic > 130:
        risk += 0.05
    if ldl > 160:
        risk += 0.1
    elif ldl > 130:
        risk += 0.05
    if hdl < 40:
        risk += 0.05
    if smoking == "Current":
        risk += 0.15
    elif smoking == "Former":
        risk += 0.05
    return min(1.0, max(0.0, risk))

def stable_uuid_for_patient(pid: str) -> str:
    """Genera un UUID v5 determinista usando un namespace fijo + patient_id."""
    namespace = uuid.UUID("00000000-0000-0000-0000-000000000001")
    return str(uuid.uuid5(namespace, pid))

def generate_synthetic_patients(**context):
    """
    Genera pacientes sintéticos y devuelve una lista con sus campos clínicos y de estilo de vida.
    Produce además un resumen clínico en texto que se usará para embeddings.
    """
    import numpy as np

    # Precedencia de parámetros: Airflow params -> Variable -> default
    params = context.get('params', {}) or {}
    num_patients = int(params.get('num_patients', VAR_PATIENTS))
    seed = int(params.get('seed', VAR_SEED))

    print(f"[gen] Generating {num_patients} patients with seed {seed}")
    set_seeds(seed)

    symptoms_pool = [
        "polyuria", "polydipsia", "fatigue", "blurred vision",
        "slow healing wounds", "tingling feet", "numbness in extremities",
        "frequent infections", "unexplained weight loss", "increased hunger",
        "dry skin", "irritability", "fruity breath odor"
    ]
    complications_pool = [
        "diabetic retinopathy", "diabetic neuropathy", "diabetic nephropathy",
        "cardiovascular disease", "peripheral artery disease", "foot ulcers",
        "gastroparesis", "erectile dysfunction", "hearing impairment",
        "skin conditions", "Alzheimer's disease risk"
    ]
    comorbidities_pool = [
        "hypertension", "hyperlipidemia", "obesity", "sleep apnea",
        "fatty liver disease", "PCOS", "thyroid disorders", "depression",
        "anxiety", "osteoarthritis", "GERD", "vitamin D deficiency"
    ]
    medications_t2dm = [
        "Metformin 1000mg BID", "Metformin 500mg BID", "Metformin XR 1500mg daily",
        "Glipizide 5mg daily", "Glimepiride 2mg daily", "Glyburide 5mg BID",
        "Sitagliptin 100mg daily", "Linagliptin 5mg daily", "Saxagliptin 5mg daily",
        "Empagliflozin 10mg daily", "Dapagliflozin 10mg daily", "Canagliflozin 100mg daily",
        "Liraglutide 1.8mg daily", "Semaglutide 1mg weekly", "Dulaglutide 1.5mg weekly",
        "Pioglitazone 30mg daily", "Insulin glargine 20 units daily", "Insulin aspart TID"
    ]
    medications_other = [
        "Lisinopril 10mg daily", "Amlodipine 5mg daily", "Metoprolol 50mg BID",
        "Atorvastatin 40mg daily", "Rosuvastatin 20mg daily", "Aspirin 81mg daily",
        "Losartan 50mg daily", "Hydrochlorothiazide 25mg daily"
    ]

    patients: List[Dict[str, Any]] = []

    for i in range(num_patients):
        age = int(np.random.normal(55, 15))
        age = max(18, min(95, age))
        gender = random.choice(["Male", "Female"])
        diabetes_type = "Type 2" if random.random() > 0.1 else "Type 1"
        years_since_diagnosis = max(0, np.random.exponential(5))

        hba1c_baseline = max(6.5, min(14, np.random.normal(9.5, 2.0)))
        treatment_effect = np.random.normal(-1.5, 1.0)
        hba1c_current = max(5.5, min(14, hba1c_baseline + treatment_effect))

        glucose_fasting = 28.7 * hba1c_current - 46.7 + np.random.normal(0, 15)
        glucose_random = glucose_fasting + np.random.uniform(20, 80)

        bmi = np.random.normal(30, 5) if diabetes_type == "Type 2" else np.random.normal(25, 4)
        bmi = max(18, min(45, bmi))

        bp_systolic = int(np.random.normal(130 + (age - 50) * 0.3, 15))
        bp_diastolic = int(np.random.normal(80 + (age - 50) * 0.1, 10))

        creatinine = max(0.5, min(5.0, np.random.normal(1.0 + years_since_diagnosis * 0.02, 0.3)))
        egfr = max(15, 175 * (creatinine ** -1.154) * (age ** -0.203) * (0.742 if gender == "Female" else 1))

        ldl = np.random.normal(100, 30)
        hdl = np.random.normal(45 if gender == "Male" else 55, 10)
        triglycerides = np.random.normal(150, 50)
        acr = np.random.exponential(30) if years_since_diagnosis > 5 else np.random.exponential(10)

        symptom_lambda = max(0.5, (hba1c_current - 7) * 1.5)
        num_symptoms = min(len(symptoms_pool), int(np.random.poisson(symptom_lambda)))
        symptoms = random.sample(symptoms_pool, max(0, num_symptoms))

        complication_risk = min(1.0, years_since_diagnosis * 0.05 + max(0, (hba1c_current - 7) * 0.1))
        complication_prob = min(0.8, complication_risk * 0.3)
        num_complications = np.random.binomial(len(complications_pool), complication_prob)
        complications = random.sample(complications_pool, min(len(complications_pool), num_complications))

        comorbidity_lambda = max(0.5, 2 + (age - 50) * 0.02)
        num_comorbidities = min(len(comorbidities_pool), int(np.random.poisson(comorbidity_lambda)))
        comorbidities = random.sample(comorbidities_pool, num_comorbidities)

        if diabetes_type == "Type 2":
            if hba1c_current < 7.5:
                diabetes_meds = random.sample(medications_t2dm[:6], 1)
            elif hba1c_current < 9:
                diabetes_meds = random.sample(medications_t2dm[:12], 2)
            else:
                diabetes_meds = random.sample(medications_t2dm, min(3, len(medications_t2dm)))
        else:
            diabetes_meds = ["Insulin glargine 30 units daily", "Insulin aspart TID"]

        other_meds = random.sample(medications_other, min(len(comorbidities), len(medications_other)))
        all_medications = diabetes_meds + other_meds

        adherence = min(100, max(40, np.random.normal(80, 15)))
        smoking = random.choices(["Never", "Former", "Current"], weights=[0.5, 0.3, 0.2])[0]
        alcohol = random.choices(["None", "Moderate", "Heavy"], weights=[0.4, 0.5, 0.1])[0]
        exercise = max(0, np.random.normal(3, 2))
        diet_score = min(10, max(1, int(np.random.normal(6, 2))))

        cv_risk = calculate_cv_risk(age, gender, bp_systolic, ldl, hdl, smoking, diabetes_type)
        ckd_risk = min(1.0, max(0.0, creatinine * 0.2 + acr * 0.001))
        retinopathy_risk = min(1.0, max(0.0, years_since_diagnosis * 0.05 + max(0, (hba1c_current - 7) * 0.1)))
        neuropathy_risk = min(1.0, max(0.0, years_since_diagnosis * 0.04 + max(0, (hba1c_current - 7) * 0.08)))

        hba1c_change = hba1c_current - hba1c_baseline
        if hba1c_change < -1.5:
            response = "Excellent"
        elif hba1c_change < -0.5:
            response = "Good"
        elif hba1c_change < 0.5:
            response = "Moderate"
        else:
            response = "Poor"

        weight_change = np.random.normal(-2 if "GLP-1" in str(all_medications) else 1, 3)
        hosp_lambda = max(0.1, 0.1 + (hba1c_current - 7) * 0.05 + len(complications) * 0.1)
        hospitalizations = np.random.poisson(hosp_lambda)
        er_visits = np.random.poisson(hosp_lambda * 2)

        insurance = random.choices(["Private", "Medicare", "Medicaid", "Uninsured"], weights=[0.4, 0.3, 0.2, 0.1])[0]
        ses_score = min(10, max(1, int(np.random.normal(6, 2))))

        clinical_summary = f"""
        {age} year old {gender} with {diabetes_type} diabetes for {years_since_diagnosis:.1f} years.
        Current HbA1c: {hba1c_current:.1f}%, Baseline: {hba1c_baseline:.1f}%.
        BMI: {bmi:.1f}, BP: {bp_systolic}/{bp_diastolic}.
        Symptoms: {', '.join(symptoms) if symptoms else 'none'}.
        Complications: {', '.join(complications) if complications else 'none'}.
        Comorbidities: {', '.join(comorbidities) if comorbidities else 'none'}.
        Medications: {', '.join(all_medications)}.
        Labs: Creatinine {creatinine:.1f}, eGFR {egfr:.0f}, LDL {ldl:.0f}, HDL {hdl:.0f}.
        Lifestyle: {smoking} smoker, {alcohol} alcohol, {exercise:.1f} hours exercise/week.
        Treatment response: {response} with HbA1c change of {hba1c_change:.1f}%.
        Risk scores: CV {cv_risk:.1%}, CKD {ckd_risk:.1%}, Retinopathy {retinopathy_risk:.1%}.
        """.strip()

        pid = f"P{str(i + 1).zfill(6)}"
        patient = {
            'patient_id': pid,
            'age': age, 'gender': gender, 'diabetes_type': diabetes_type,
            'years_since_diagnosis': round(years_since_diagnosis, 1),
            'hba1c_current': round(hba1c_current, 1),
            'hba1c_baseline': round(hba1c_baseline, 1),
            'glucose_fasting': round(glucose_fasting, 0),
            'glucose_random': round(glucose_random, 0),
            'bmi': round(bmi, 1),
            'blood_pressure_systolic': bp_systolic,
            'blood_pressure_diastolic': bp_diastolic,
            'creatinine': round(creatinine, 2),
            'egfr': round(egfr, 1),
            'ldl_cholesterol': round(ldl, 0),
            'hdl_cholesterol': round(hdl, 0),
            'triglycerides': round(triglycerides, 0),
            'albumin_creatinine_ratio': round(acr, 1),
            'symptoms': symptoms,
            'complications': complications,
            'comorbidities': comorbidities,
            'medications': all_medications,
            'medication_adherence': round(adherence, 1),
            'smoking_status': smoking,
            'alcohol_use': alcohol,
            'exercise_weekly_hours': round(exercise, 1),
            'diet_quality_score': diet_score,
            'cardiovascular_risk_score': round(cv_risk, 3),
            'kidney_disease_risk': round(ckd_risk, 3),
            'retinopathy_risk': round(retinopathy_risk, 3),
            'neuropathy_risk': round(neuropathy_risk, 3),
            'treatment_response': response,
            'hba1c_change': round(hba1c_change, 1),
            'weight_change': round(weight_change, 1),
            'hospitalizations_past_year': hospitalizations,
            'emergency_visits_past_year': er_visits,
            'insurance_type': insurance,
            'socioeconomic_score': ses_score,
            'clinical_summary': clinical_summary,
            'last_updated': datetime.utcnow().isoformat() + 'Z',
            'data_quality_score': 0.95
        }
        patients.append(patient)

        if (i + 1) % 100 == 0:
            print(f"[gen] Generated {i + 1}/{num_patients}")

    avg_hba1c = sum(p['hba1c_current'] for p in patients) / len(patients)
    controlled = sum(1 for p in patients if p['hba1c_current'] < 7) / len(patients) * 100
    with_complications = sum(1 for p in patients if p['complications']) / len(patients) * 100
    print(f"[gen] Summary: {len(patients)} patients | Avg HbA1c={avg_hba1c:.1f}% | <7%={controlled:.1f}% | Complications={with_complications:.1f}%")

    return {"patients": patients, "seed": seed}

def generate_patient_embeddings(**context):
    """
    Genera embeddings para los pacientes a partir del campo 'clinical_summary'.
    Usa el modelo configurado en params/Variable y devuelve los pacientes
    con una clave adicional 'embedding' (lista de números).
    """
    from sentence_transformers import SentenceTransformer
    ti = context['task_instance']
    payload = ti.xcom_pull(task_ids='generate_patients') or {}
    patients = payload.get("patients", [])
    if not patients:
        print("[embed] No patients to embed")
        return {"patients": []}

    model_name = context.get('params', {}).get('embedding_model', VAR_EMB_MODEL)
    print(f"[embed] Loading embedding model: {model_name}")
    try:
        model = SentenceTransformer(model_name)
    except Exception as e:
        print(f"[embed] Failed to load {model_name}: {e} | Falling back to all-MiniLM-L6-v2")
        model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")

    texts = [p["clinical_summary"] for p in patients]
    embeddings = model.encode(texts, show_progress_bar=True, convert_to_numpy=True)
    for p, vec in zip(patients, embeddings):
        p["embedding"] = vec.tolist()
    print(f"[embed] Embedded {len(patients)} patients")
    return {"patients": patients}

def load_patients_to_weaviate(**context):
    """
    Carga los pacientes (con embeddings) en Weaviate mediante lotes.
    Aplica upsert: si el patient_id ya existe (UUID estable), reemplaza el objeto.
    Guarda métricas en la Variable 'last_patient_ingestion'.
    """
    import weaviate
    ti = context['task_instance']
    payload = ti.xcom_pull(task_ids='generate_embeddings') or {}
    patients = payload.get("patients", [])
    if not patients:
        print("[load] No patients to load")
        return {"loaded": 0, "replaced": 0, "failed": 0}

    client = weaviate_client()
    stats = {"loaded": 0, "replaced": 0, "failed": 0}

    # Configuración de batch
    client.batch.configure(
        batch_size=VAR_BATCH_SIZE,
        dynamic=True,
        timeout_retries=3
    )

    batch_objects = 0
    with client.batch as batch:
        for idx, patient in enumerate(patients, start=1):
            try:
                embedding = patient.pop("embedding")
                pid = patient["patient_id"]
                obj_uuid = stable_uuid_for_patient(pid)

                # Intento de alta por batch; si existe, replace
                try:
                    batch.add_data_object(
                        data_object=patient,
                        class_name=PATIENT_CLASS,
                        uuid=obj_uuid,
                        vector=embedding,
                    )
                    stats["loaded"] += 1
                    batch_objects += 1
                except Exception as e:
                    # Fallback: replace (upsert)
                    try:
                        client.data_object.replace(
                            data_object=patient,
                            class_name=PATIENT_CLASS,
                            uuid=obj_uuid,
                            vector=embedding,
                        )
                        stats["replaced"] += 1
                    except Exception as e2:
                        stats["failed"] += 1
                        print(f"[load] Failed upsert {pid}: {e2}")
                        continue

                if batch_objects and batch_objects % 500 == 0:
                    print(f"[load] Batched {batch_objects} objects so far")

            except Exception as e:
                stats["failed"] += 1
                print(f"[load] Error processing patient: {e}")

    print(f"[load] COMPLETE | loaded={stats['loaded']}, replaced={stats['replaced']}, failed={stats['failed']}")
    Variable.set("last_patient_ingestion", json.dumps({
        'timestamp': datetime.utcnow().isoformat() + 'Z',
        'stats': stats,
        'total_processed': len(patients),
        'batch_size': VAR_BATCH_SIZE
    }))
    return stats

# ---------------------------
# Definición del DAG
# ---------------------------
with DAG(
    dag_id='synthetic_patient_data_ingestion_v2',
    default_args=default_args,
    description='Generate & ingest synthetic diabetes patients with embeddings (idempotent, batched, reproducible)',
    schedule=None,  # ejecución manual salvo que configures un cron
    catchup=False,
    params={
        'num_patients': VAR_PATIENTS,
        'embedding_model': VAR_EMB_MODEL,
        'seed': VAR_SEED
    },
    tags=['healthcare', 'patients', 'synthetic', 'diabetes', 'weaviate'],
    max_active_runs=1,
) as dag:

    setup_deps = PythonOperator(
        task_id='setup_dependencies',
        python_callable=setup_dependencies,
    )

    init_collection = PythonOperator(
        task_id='initialize_collection',
        python_callable=initialize_patient_collection,
    )

    generate_patients = PythonOperator(
        task_id='generate_patients',
        python_callable=generate_synthetic_patients,
    )

    create_embeddings = PythonOperator(
        task_id='generate_embeddings',
        python_callable=generate_patient_embeddings,
    )

    load_data = PythonOperator(
        task_id='load_to_weaviate',
        python_callable=load_patients_to_weaviate,
    )

    setup_deps >> init_collection >> generate_patients >> create_embeddings >> load_data
