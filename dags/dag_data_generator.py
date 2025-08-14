# Synthetic Patient Data Ingestion DAG for Diabetes
import subprocess
import sys
from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.models import Variable
import json
import os
import hashlib
from typing import Dict, List, Any
import random
import numpy as np

def install_packages():
    """Install required packages at runtime"""
    packages = ['sentence-transformers>=2.2.3', 'numpy', 'pandas']
    for package in packages:
        try:
            subprocess.check_call([sys.executable, '-m', 'pip', 'install', package])
            print(f"✅ Installed {package}")
        except Exception as e:
            print(f"⚠️ Failed to install {package}: {str(e)}")

# Configuration
WEAVIATE_URL = os.getenv("WEAVIATE_URL", "http://weaviate.weaviate.svc.cluster.local:8080")

# Use a medical-specific embedding model
EMBEDDING_MODEL = "pritamdeka/S-PubMedBert-MS-MARCO"

# Collection schema for patient records
PATIENT_SCHEMA = {
    "class": "DiabetesPatients",
    "description": "Synthetic diabetes patient records for similarity matching",
    "vectorizer": "none",
    "properties": [
        {"name": "patient_id", "dataType": ["text"], "description": "Unique patient identifier"},
        {"name": "age", "dataType": ["int"], "description": "Patient age"},
        {"name": "gender", "dataType": ["text"], "description": "Patient gender"},
        {"name": "diabetes_type", "dataType": ["text"], "description": "Type 1 or Type 2"},
        {"name": "years_since_diagnosis", "dataType": ["number"], "description": "Years since diabetes diagnosis"},
        
        # Clinical measurements
        {"name": "hba1c_current", "dataType": ["number"], "description": "Current HbA1c level"},
        {"name": "hba1c_baseline", "dataType": ["number"], "description": "Baseline HbA1c at diagnosis"},
        {"name": "glucose_fasting", "dataType": ["number"], "description": "Fasting glucose mg/dL"},
        {"name": "glucose_random", "dataType": ["number"], "description": "Random glucose mg/dL"},
        {"name": "bmi", "dataType": ["number"], "description": "Body Mass Index"},
        {"name": "blood_pressure_systolic", "dataType": ["int"], "description": "Systolic BP"},
        {"name": "blood_pressure_diastolic", "dataType": ["int"], "description": "Diastolic BP"},
        
        # Lab results
        {"name": "creatinine", "dataType": ["number"], "description": "Creatinine mg/dL"},
        {"name": "egfr", "dataType": ["number"], "description": "Estimated GFR"},
        {"name": "ldl_cholesterol", "dataType": ["number"], "description": "LDL cholesterol mg/dL"},
        {"name": "hdl_cholesterol", "dataType": ["number"], "description": "HDL cholesterol mg/dL"},
        {"name": "triglycerides", "dataType": ["number"], "description": "Triglycerides mg/dL"},
        {"name": "albumin_creatinine_ratio", "dataType": ["number"], "description": "Urine ACR"},
        
        # Symptoms and complications
        {"name": "symptoms", "dataType": ["text[]"], "description": "Current symptoms"},
        {"name": "complications", "dataType": ["text[]"], "description": "Diabetic complications"},
        {"name": "comorbidities", "dataType": ["text[]"], "description": "Other conditions"},
        
        # Medications
        {"name": "medications", "dataType": ["text[]"], "description": "Current medications"},
        {"name": "medication_adherence", "dataType": ["number"], "description": "Adherence percentage"},
        
        # Lifestyle factors
        {"name": "smoking_status", "dataType": ["text"], "description": "Smoking status"},
        {"name": "alcohol_use", "dataType": ["text"], "description": "Alcohol consumption"},
        {"name": "exercise_weekly_hours", "dataType": ["number"], "description": "Exercise hours per week"},
        {"name": "diet_quality_score", "dataType": ["int"], "description": "Diet quality 1-10"},
        
        # Risk scores
        {"name": "cardiovascular_risk_score", "dataType": ["number"], "description": "10-year CV risk"},
        {"name": "kidney_disease_risk", "dataType": ["number"], "description": "CKD progression risk"},
        {"name": "retinopathy_risk", "dataType": ["number"], "description": "Retinopathy risk"},
        {"name": "neuropathy_risk", "dataType": ["number"], "description": "Neuropathy risk"},
        
        # Treatment response
        {"name": "treatment_response", "dataType": ["text"], "description": "Response to treatment"},
        {"name": "hba1c_change", "dataType": ["number"], "description": "HbA1c change from baseline"},
        {"name": "weight_change", "dataType": ["number"], "description": "Weight change in kg"},
        
        # Hospitalizations
        {"name": "hospitalizations_past_year", "dataType": ["int"], "description": "Hospital admissions"},
        {"name": "emergency_visits_past_year", "dataType": ["int"], "description": "ER visits"},
        
        # Social determinants
        {"name": "insurance_type", "dataType": ["text"], "description": "Insurance coverage"},
        {"name": "socioeconomic_score", "dataType": ["int"], "description": "SES score 1-10"},
        
        # Embedding and metadata
        {"name": "clinical_summary", "dataType": ["text"], "description": "Text summary for embedding"},
        {"name": "last_updated", "dataType": ["date"], "description": "Last update timestamp"},
        {"name": "data_quality_score", "dataType": ["number"], "description": "Data completeness score"}
    ]
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

def setup_dependencies():
    """Install packages and import them"""
    install_packages()
    
    global SentenceTransformer, weaviate
    
    try:
        from sentence_transformers import SentenceTransformer
        print("✅ Sentence Transformers imported successfully")
    except ImportError as e:
        print(f"❌ Failed to import Sentence Transformers: {str(e)}")
        raise
    
    try:
        import weaviate
        print("✅ Weaviate client imported successfully")
    except ImportError as e:
        print(f"❌ Failed to import Weaviate: {str(e)}")
        raise
    
    return True

def initialize_patient_collection():
    """Create the DiabetesPatients collection in Weaviate if it doesn't exist"""
    try:
        import weaviate
        client = weaviate.Client(url=WEAVIATE_URL)
        
        schema = client.schema.get()
        existing_classes = [c['class'] for c in schema.get('classes', [])]
        
        if PATIENT_SCHEMA['class'] not in existing_classes:
            client.schema.create_class(PATIENT_SCHEMA)
            print(f"✅ Created collection: {PATIENT_SCHEMA['class']}")
        else:
            print(f"ℹ️ Collection {PATIENT_SCHEMA['class']} already exists")
        
        # Get collection info
        try:
            collection_info = client.query.aggregate(PATIENT_SCHEMA['class']) \
                .with_meta_count() \
                .do()
            
            current_count = collection_info['data']['Aggregate'][PATIENT_SCHEMA['class']][0]['meta']['count']
            print(f"📊 Current patients in collection: {current_count}")
        except:
            print("📊 Collection is empty or new")
        
        return True
        
    except Exception as e:
        print(f"❌ Error initializing Weaviate: {str(e)}")
        raise

def generate_synthetic_patients(**context):
    """Generate realistic synthetic diabetes patient data"""
    
    params = context.get('params', {})
    num_patients = params.get('num_patients', 500)  # Default 500 patients
    
    print(f"🏥 Generating {num_patients} synthetic diabetes patients")
    
    patients = []
    
    # Define realistic distributions
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
    
    # Generate patients
    for i in range(num_patients):
        # Demographics
        age = int(np.random.normal(55, 15))
        age = max(18, min(95, age))  # Clamp to reasonable range
        gender = random.choice(["Male", "Female"])
        diabetes_type = "Type 2" if random.random() > 0.1 else "Type 1"  # 90% Type 2
        
        # Disease duration affects complications
        years_since_diagnosis = max(0, np.random.exponential(5))
        
        # HbA1c - current and baseline
        hba1c_baseline = np.random.normal(9.5, 2.0)
        hba1c_baseline = max(6.5, min(14, hba1c_baseline))
        
        # Treatment affects current HbA1c
        treatment_effect = np.random.normal(-1.5, 1.0)  # Average reduction
        hba1c_current = hba1c_baseline + treatment_effect
        hba1c_current = max(5.5, min(14, hba1c_current))
        
        # Glucose levels correlate with HbA1c
        glucose_fasting = 28.7 * hba1c_current - 46.7 + np.random.normal(0, 15)
        glucose_random = glucose_fasting + np.random.uniform(20, 80)
        
        # BMI - higher in Type 2
        if diabetes_type == "Type 2":
            bmi = np.random.normal(30, 5)
        else:
            bmi = np.random.normal(25, 4)
        bmi = max(18, min(45, bmi))
        
        # Blood pressure - often elevated in diabetes
        bp_systolic = int(np.random.normal(130 + (age-50)*0.3, 15))
        bp_diastolic = int(np.random.normal(80 + (age-50)*0.1, 10))
        
        # Kidney function - worse with longer disease duration
        creatinine = np.random.normal(1.0 + years_since_diagnosis*0.02, 0.3)
        creatinine = max(0.5, min(5.0, creatinine))
        egfr = max(15, 175 * (creatinine**-1.154) * (age**-0.203) * (0.742 if gender == "Female" else 1))
        
        # Lipids
        ldl = np.random.normal(100, 30)
        hdl = np.random.normal(45 if gender == "Male" else 55, 10)
        triglycerides = np.random.normal(150, 50)
        
        # Albumin-creatinine ratio - indicates kidney damage
        acr = np.random.exponential(30) if years_since_diagnosis > 5 else np.random.exponential(10)
        
        # Symptoms - more with poor control
        symptom_lambda = max(0.5, (hba1c_current - 7) * 1.5)  # Ensure positive value
        num_symptoms = min(len(symptoms_pool), int(np.random.poisson(symptom_lambda)))
        symptoms = random.sample(symptoms_pool, max(0, num_symptoms))
        
        # Complications - increase with disease duration and poor control
        complication_risk = min(1.0, years_since_diagnosis * 0.05 + max(0, (hba1c_current - 7) * 0.1))
        complication_prob = min(0.8, complication_risk * 0.3)  # Cap probability at 0.8
        num_complications = np.random.binomial(len(complications_pool), complication_prob)
        complications = random.sample(complications_pool, min(len(complications_pool), num_complications))
        
        # Comorbidities - common in diabetes
        comorbidity_lambda = max(0.5, 2 + (age - 50) * 0.02)  # Age-adjusted, ensure positive
        num_comorbidities = min(len(comorbidities_pool), int(np.random.poisson(comorbidity_lambda)))
        comorbidities = random.sample(comorbidities_pool, num_comorbidities)
        
        # Medications
        diabetes_meds = []
        if diabetes_type == "Type 2":
            if hba1c_current < 7.5:
                diabetes_meds = random.sample(medications_t2dm[:6], 1)  # Monotherapy
            elif hba1c_current < 9:
                diabetes_meds = random.sample(medications_t2dm[:12], 2)  # Dual therapy
            else:
                diabetes_meds = random.sample(medications_t2dm, min(3, len(medications_t2dm)))  # Triple+ therapy
        else:  # Type 1
            diabetes_meds = ["Insulin glargine 30 units daily", "Insulin aspart TID"]
        
        # Add other medications for comorbidities
        other_meds = random.sample(medications_other, min(len(comorbidities), len(medications_other)))
        all_medications = diabetes_meds + other_meds
        
        # Medication adherence
        adherence = min(100, max(40, np.random.normal(80, 15)))
        
        # Lifestyle factors
        smoking = random.choices(["Never", "Former", "Current"], weights=[0.5, 0.3, 0.2])[0]
        alcohol = random.choices(["None", "Moderate", "Heavy"], weights=[0.4, 0.5, 0.1])[0]
        exercise = max(0, np.random.normal(3, 2))
        diet_score = min(10, max(1, int(np.random.normal(6, 2))))
        
        # Calculate risk scores (ensure all are between 0 and 1)
        cv_risk = calculate_cv_risk(age, gender, bp_systolic, ldl, hdl, smoking, diabetes_type)
        ckd_risk = min(1.0, max(0.0, creatinine * 0.2 + acr * 0.001))
        retinopathy_risk = min(1.0, max(0.0, years_since_diagnosis * 0.05 + max(0, (hba1c_current - 7) * 0.1)))
        neuropathy_risk = min(1.0, max(0.0, years_since_diagnosis * 0.04 + max(0, (hba1c_current - 7) * 0.08)))
        
        # Treatment response
        hba1c_change = hba1c_current - hba1c_baseline
        if hba1c_change < -1.5:
            response = "Excellent"
        elif hba1c_change < -0.5:
            response = "Good"
        elif hba1c_change < 0.5:
            response = "Moderate"
        else:
            response = "Poor"
        
        # Weight change (some meds cause weight gain/loss)
        weight_change = np.random.normal(-2 if "GLP-1" in str(all_medications) else 1, 3)
        
        # Healthcare utilization
        hosp_lambda = max(0.1, 0.1 + (hba1c_current - 7) * 0.05 + len(complications) * 0.1)  # Ensure positive
        hospitalizations = np.random.poisson(hosp_lambda)
        er_visits = np.random.poisson(hosp_lambda * 2)
        
        # Social determinants
        insurance = random.choices(
            ["Private", "Medicare", "Medicaid", "Uninsured"],
            weights=[0.4, 0.3, 0.2, 0.1]
        )[0]
        ses_score = min(10, max(1, int(np.random.normal(6, 2))))
        
        # Create clinical summary for embedding
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
        """
        
        patient = {
            'patient_id': f"P{str(i+1).zfill(6)}",
            'age': age,
            'gender': gender,
            'diabetes_type': diabetes_type,
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
            'clinical_summary': clinical_summary.strip(),
            'last_updated': datetime.now().isoformat() + 'Z',
            'data_quality_score': 0.95  # High quality synthetic data
        }
        
        patients.append(patient)
        
        if (i + 1) % 50 == 0:
            print(f"📊 Generated {i + 1}/{num_patients} patients")
    
    print(f"✅ Successfully generated {len(patients)} synthetic patients")
    
    # Basic statistics
    avg_hba1c = np.mean([p['hba1c_current'] for p in patients])
    controlled = len([p for p in patients if p['hba1c_current'] < 7]) / len(patients) * 100
    with_complications = len([p for p in patients if p['complications']]) / len(patients) * 100
    
    print(f"\n📈 Population Statistics:")
    print(f"   Average HbA1c: {avg_hba1c:.1f}%")
    print(f"   Well-controlled (<7%): {controlled:.1f}%")
    print(f"   With complications: {with_complications:.1f}%")
    
    return patients

def calculate_cv_risk(age, gender, bp_systolic, ldl, hdl, smoking, diabetes):
    """Calculate simplified cardiovascular risk score"""
    # Simplified ASCVD risk calculator
    risk = 0.1  # Base risk with diabetes
    
    # Age factor
    risk += max(0, (age - 40) * 0.01)
    
    # Gender
    if gender == "Male":
        risk += 0.05
    
    # Blood pressure
    if bp_systolic > 140:
        risk += 0.1
    elif bp_systolic > 130:
        risk += 0.05
    
    # Cholesterol
    if ldl > 160:
        risk += 0.1
    elif ldl > 130:
        risk += 0.05
    
    if hdl < 40:
        risk += 0.05
    
    # Smoking
    if smoking == "Current":
        risk += 0.15
    elif smoking == "Former":
        risk += 0.05
    
    return min(1.0, max(0.0, risk))  # Ensure between 0 and 1

def generate_patient_embeddings(**context):
    """Generate embeddings for patient clinical summaries"""
    from sentence_transformers import SentenceTransformer
    
    ti = context['task_instance']
    patients = ti.xcom_pull(task_ids='generate_patients')
    
    if not patients:
        print("⚠️ No patients to process")
        return []
    
    print(f"🧮 Generating embeddings for {len(patients)} patients")
    print(f"📦 Using embedding model: {EMBEDDING_MODEL}")
    
    # Initialize embedding model
    try:
        model = SentenceTransformer(EMBEDDING_MODEL)
        print("✅ Medical embedding model loaded")
    except Exception as e:
        print(f"⚠️ Error loading medical model: {str(e)}")
        print("🔄 Falling back to general model")
        model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
    
    patients_with_embeddings = []
    
    for i, patient in enumerate(patients):
        try:
            # Use clinical summary for embedding
            embedding_text = patient['clinical_summary']
            
            # Generate embedding
            embedding = model.encode(embedding_text).tolist()
            
            # Add embedding to patient
            patient_with_embedding = {
                **patient,
                'embedding': embedding
            }
            
            patients_with_embeddings.append(patient_with_embedding)
            
            if (i + 1) % 50 == 0:
                print(f"📊 Processed {i + 1}/{len(patients)} patients")
            
        except Exception as e:
            print(f"⚠️ Error processing patient {patient.get('patient_id', 'unknown')}: {str(e)}")
            continue
    
    print(f"✅ Generated embeddings for {len(patients_with_embeddings)} patients")
    
    return patients_with_embeddings

def load_patients_to_weaviate(**context):
    """Load patient records with embeddings into Weaviate"""
    import weaviate
    
    ti = context['task_instance']
    patients = ti.xcom_pull(task_ids='generate_embeddings')
    
    if not patients:
        print("⚠️ No patients to load")
        return {'loaded': 0, 'skipped': 0, 'failed': 0}
    
    print(f"📤 Loading {len(patients)} patients to Weaviate")
    
    client = weaviate.Client(url=WEAVIATE_URL)
    
    stats = {
        'loaded': 0,
        'skipped': 0,
        'failed': 0
    }
    
    # Check existing patients to avoid duplicates
    existing_ids = set()
    try:
        result = client.query \
            .get(PATIENT_SCHEMA['class'], ['patient_id']) \
            .with_limit(10000) \
            .do()
        
        if 'data' in result and 'Get' in result['data']:
            existing_ids = {
                item['patient_id'] 
                for item in result['data']['Get'][PATIENT_SCHEMA['class']]
            }
        print(f"📊 Found {len(existing_ids)} existing patients")
    except Exception as e:
        print(f"⚠️ Could not check existing patients: {str(e)}")
    
    # Load patients
    for patient in patients:
        try:
            # Check if already exists
            if patient['patient_id'] in existing_ids:
                print(f"⏭️ Skipping duplicate: {patient['patient_id']}")
                stats['skipped'] += 1
                continue
            
            # Extract embedding
            embedding = patient.pop('embedding')
            
            # Create object in Weaviate
            client.data_object.create(
                data_object=patient,
                class_name=PATIENT_SCHEMA['class'],
                vector=embedding
            )
            
            stats['loaded'] += 1
            
            if stats['loaded'] % 50 == 0:
                print(f"✅ Loaded {stats['loaded']} patients")
            
        except Exception as e:
            print(f"❌ Failed to load patient {patient.get('patient_id', 'unknown')}: {str(e)}")
            stats['failed'] += 1
    
    # Final statistics
    print(f"\n📊 LOADING COMPLETE:")
    print(f"   ✅ Loaded: {stats['loaded']}")
    print(f"   ⏭️ Skipped: {stats['skipped']}")
    print(f"   ❌ Failed: {stats['failed']}")
    
    # Store stats
    Variable.set("last_patient_ingestion", json.dumps({
        'timestamp': datetime.now().isoformat(),
        'stats': stats,
        'total_processed': len(patients)
    }))
    
    return stats

# Create the DAG
with DAG(
    'synthetic_patient_data_ingestion',
    default_args=default_args,
    description='Generate and ingest synthetic diabetes patient data for similarity matching',
    schedule=None,  # Manual trigger
    catchup=False,
    params={
        'num_patients': 500  # Number of synthetic patients to generate
    },
    tags=['healthcare', 'patients', 'synthetic', 'diabetes'],
    max_active_runs=1,
) as dag:

    # Task 0: Setup dependencies
    setup_deps = PythonOperator(
        task_id='setup_dependencies',
        python_callable=setup_dependencies,
    )

    # Task 1: Initialize Weaviate collection
    init_collection = PythonOperator(
        task_id='initialize_collection',
        python_callable=initialize_patient_collection,
    )

    # Task 2: Generate synthetic patients
    generate_patients = PythonOperator(
        task_id='generate_patients',
        python_callable=generate_synthetic_patients,
    )

    # Task 3: Generate embeddings
    create_embeddings = PythonOperator(
        task_id='generate_embeddings',
        python_callable=generate_patient_embeddings,
    )

    # Task 4: Load to Weaviate
    load_data = PythonOperator(
        task_id='load_to_weaviate',
        python_callable=load_patients_to_weaviate,
    )
 
    # Define task dependencies
    setup_deps >> init_collection >> generate_patients >> create_embeddings >> load_data