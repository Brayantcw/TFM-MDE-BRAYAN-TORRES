"""
Medical Research Validation & Query DAG
This DAG validates the ingested data and performs sample queries to demonstrate RAG capabilities
"""

import subprocess
import sys
from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.models import Variable
import json
import os
from typing import Dict, List, Any
import time

# Configuration
WEAVIATE_URL = os.getenv("WEAVIATE_URL", "http://weaviate.weaviate.svc.cluster.local:8080")
COLLECTION_NAME = "MedicalResearch"

# Medical queries to test
TEST_QUERIES = [
    {
        "query": "What are the latest treatments for Type 2 diabetes?",
        "expected_keywords": ["diabetes", "treatment", "metformin", "insulin"],
        "category": "treatment"
    },
    {
        "query": "Side effects of metformin in diabetic patients",
        "expected_keywords": ["metformin", "side effects", "adverse"],
        "category": "pharmacology"
    },
    {
        "query": "Relationship between diabetes and cardiovascular disease",
        "expected_keywords": ["diabetes", "cardiovascular", "heart", "risk"],
        "category": "comorbidity"
    },
    {
        "query": "HbA1c levels and glycemic control monitoring",
        "expected_keywords": ["HbA1c", "glycemic", "glucose", "monitoring"],
        "category": "diagnostics"
    },
    {
        "query": "Lifestyle interventions for diabetes prevention",
        "expected_keywords": ["lifestyle", "prevention", "exercise", "diet"],
        "category": "prevention"
    }
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

def install_validation_packages():
    """Install packages needed for validation"""
    packages = [
        'sentence-transformers>=2.3.0',
        'tabulate',  # For nice table output
        'matplotlib',  # For visualization
        'pandas',  # For data analysis
    ]
    
    for package in packages:
        try:
            subprocess.check_call([sys.executable, '-m', 'pip', 'install', '--quiet', package])
            print(f"✅ Installed {package}")
        except Exception as e:
            print(f"⚠️ Failed to install {package}: {str(e)}")

def validate_collection_health():
    """Check the health and statistics of the Medical Research collection"""
    import weaviate
    
    try:
        client = weaviate.Client(url=WEAVIATE_URL)
        
        print("=" * 60)
        print("🏥 MEDICAL RESEARCH COLLECTION HEALTH CHECK")
        print("=" * 60)
        
        # Check if collection exists
        schema = client.schema.get()
        collection_exists = any(c['class'] == COLLECTION_NAME for c in schema.get('classes', []))
        
        if not collection_exists:
            print(f"❌ Collection '{COLLECTION_NAME}' does not exist!")
            raise ValueError(f"Collection {COLLECTION_NAME} not found. Please run the ingestion DAG first.")
        
        print(f"✅ Collection '{COLLECTION_NAME}' exists")
        
        # Get document count
        result = client.query.aggregate(COLLECTION_NAME) \
            .with_meta_count() \
            .do()
        
        total_docs = result['data']['Aggregate'][COLLECTION_NAME][0]['meta']['count']
        print(f"📊 Total documents: {total_docs}")
        
        if total_docs == 0:
            raise ValueError("No documents in collection. Please run ingestion DAG first.")
        
        # Get sample documents to check quality
        sample_result = client.query \
            .get(COLLECTION_NAME, ['pmid', 'title', 'abstract', 'mesh_terms', 'publication_date', 'journal']) \
            .with_limit(5) \
            .do()
        
        sample_docs = sample_result['data']['Get'][COLLECTION_NAME]
        
        # Calculate quality metrics
        quality_metrics = {
            'total_documents': total_docs,
            'sample_size': len(sample_docs),
            'docs_with_abstracts': sum(1 for doc in sample_docs if doc.get('abstract')),
            'docs_with_mesh_terms': sum(1 for doc in sample_docs if doc.get('mesh_terms')),
            'avg_abstract_length': sum(len(doc.get('abstract', '')) for doc in sample_docs) / len(sample_docs) if sample_docs else 0,
            'unique_journals': len(set(doc.get('journal', 'Unknown') for doc in sample_docs))
        }
        
        print("\n📈 Quality Metrics:")
        print(f"   • Documents with abstracts: {quality_metrics['docs_with_abstracts']}/{quality_metrics['sample_size']}")
        print(f"   • Documents with MeSH terms: {quality_metrics['docs_with_mesh_terms']}/{quality_metrics['sample_size']}")
        print(f"   • Average abstract length: {quality_metrics['avg_abstract_length']:.0f} characters")
        print(f"   • Unique journals in sample: {quality_metrics['unique_journals']}")
        
        # Display sample documents
        print("\n📚 Sample Documents:")
        for i, doc in enumerate(sample_docs[:3], 1):
            print(f"\n   {i}. PMID: {doc.get('pmid', 'N/A')}")
            print(f"      Title: {doc.get('title', 'N/A')[:80]}...")
            print(f"      Journal: {doc.get('journal', 'N/A')}")
            print(f"      MeSH Terms: {', '.join(doc.get('mesh_terms', [])[:3])}")
        
        # Store metrics
        Variable.set("collection_health_metrics", json.dumps(quality_metrics))
        
        return quality_metrics
        
    except Exception as e:
        print(f"❌ Error validating collection: {str(e)}")
        raise

def perform_semantic_searches(**context):
    """Perform semantic searches to validate RAG functionality"""
    import weaviate
    from sentence_transformers import SentenceTransformer
    from tabulate import tabulate
    
    try:
        client = weaviate.Client(url=WEAVIATE_URL)
        
        # Initialize embedding model
        print("🔄 Loading embedding model...")
        try:
            model = SentenceTransformer("pritamdeka/S-PubMedBert-MS-MARCO")
            print("✅ Using medical-specific model")
        except:
            model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
            print("✅ Using general model")
        
        print("\n" + "=" * 60)
        print("🔍 PERFORMING SEMANTIC SEARCHES")
        print("=" * 60)
        
        search_results = []
        
        for test_case in TEST_QUERIES:
            query = test_case['query']
            print(f"\n🔎 Query: '{query}'")
            print(f"   Category: {test_case['category']}")
            
            # Generate embedding for query
            query_embedding = model.encode(query).tolist()
            
            # Perform vector search
            result = client.query \
                .get(COLLECTION_NAME, ['title', 'abstract', 'pmid', 'journal', 'mesh_terms']) \
                .with_near_vector({
                    'vector': query_embedding,
                    'certainty': 0.7  # Similarity threshold
                }) \
                .with_limit(3) \
                .with_additional(['certainty', 'distance']) \
                .do()
            
            if 'data' in result and result['data']['Get'][COLLECTION_NAME]:
                articles = result['data']['Get'][COLLECTION_NAME]
                
                print(f"   ✅ Found {len(articles)} relevant articles:")
                
                for i, article in enumerate(articles, 1):
                    certainty = article['_additional']['certainty']
                    print(f"\n   {i}. Title: {article['title'][:70]}...")
                    print(f"      PMID: {article['pmid']}")
                    print(f"      Journal: {article['journal']}")
                    print(f"      Relevance Score: {certainty:.3f}")
                    print(f"      Abstract Preview: {article['abstract'][:150]}...")
                    
                    # Check if expected keywords are present
                    abstract_lower = article['abstract'].lower()
                    title_lower = article['title'].lower()
                    keywords_found = [kw for kw in test_case['expected_keywords'] 
                                     if kw.lower() in abstract_lower or kw.lower() in title_lower]
                    
                    if keywords_found:
                        print(f"      Keywords Found: {', '.join(keywords_found)}")
                
                # Store results
                search_results.append({
                    'query': query,
                    'category': test_case['category'],
                    'results_count': len(articles),
                    'top_score': articles[0]['_additional']['certainty'] if articles else 0,
                    'top_title': articles[0]['title'] if articles else 'None',
                    'top_pmid': articles[0]['pmid'] if articles else 'None'
                })
            else:
                print("   ❌ No results found")
                search_results.append({
                    'query': query,
                    'category': test_case['category'],
                    'results_count': 0,
                    'top_score': 0,
                    'top_title': 'None',
                    'top_pmid': 'None'
                })
        
        # Summary table
        print("\n" + "=" * 60)
        print("📊 SEARCH RESULTS SUMMARY")
        print("=" * 60)
        
        import pandas as pd
        df = pd.DataFrame(search_results)
        
        # Create summary statistics
        summary = {
            'total_queries': len(search_results),
            'successful_queries': sum(1 for r in search_results if r['results_count'] > 0),
            'avg_relevance_score': df['top_score'].mean(),
            'queries_by_category': df.groupby('category')['results_count'].mean().to_dict()
        }
        
        print(f"\n✅ Successful Queries: {summary['successful_queries']}/{summary['total_queries']}")
        print(f"📈 Average Relevance Score: {summary['avg_relevance_score']:.3f}")
        print("\n📋 Results by Category:")
        for category, avg_results in summary['queries_by_category'].items():
            print(f"   • {category}: {avg_results:.1f} avg results")
        
        # Store results
        Variable.set("semantic_search_results", json.dumps(search_results))
        Variable.set("search_summary", json.dumps(summary))
        
        return search_results
        
    except Exception as e:
        print(f"❌ Error performing searches: {str(e)}")
        raise

def test_advanced_queries(**context):
    """Test more complex medical queries with filtering and aggregation"""
    import weaviate
    from sentence_transformers import SentenceTransformer
    
    try:
        client = weaviate.Client(url=WEAVIATE_URL)
        model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
        
        print("\n" + "=" * 60)
        print("🧪 TESTING ADVANCED QUERIES")
        print("=" * 60)
        
        # Test 1: Multi-concept query
        print("\n1️⃣ Multi-Concept Query Test")
        complex_query = "diabetes complications neuropathy retinopathy nephropathy prevention management"
        embedding = model.encode(complex_query).tolist()
        
        result = client.query \
            .get(COLLECTION_NAME, ['title', 'abstract', 'mesh_terms']) \
            .with_near_vector({'vector': embedding, 'certainty': 0.65}) \
            .with_limit(5) \
            .with_additional(['certainty']) \
            .do()
        
        if result['data']['Get'][COLLECTION_NAME]:
            print(f"   ✅ Found {len(result['data']['Get'][COLLECTION_NAME])} articles on diabetes complications")
            
            # Analyze MeSH term coverage
            all_mesh_terms = []
            for article in result['data']['Get'][COLLECTION_NAME]:
                all_mesh_terms.extend(article.get('mesh_terms', []))
            
            unique_mesh = set(all_mesh_terms)
            print(f"   📊 Unique MeSH terms covered: {len(unique_mesh)}")
            print(f"   📋 Top MeSH terms: {', '.join(list(unique_mesh)[:5])}")
        
        # Test 2: Query for recent studies (using publication date if available)
        print("\n2️⃣ Temporal Query Test")
        recent_query = "latest breakthrough diabetes treatment 2024"
        embedding = model.encode(recent_query).tolist()
        
        result = client.query \
            .get(COLLECTION_NAME, ['title', 'publication_date', 'journal']) \
            .with_near_vector({'vector': embedding, 'certainty': 0.6}) \
            .with_limit(5) \
            .with_additional(['certainty']) \
            .do()
        
        if result['data']['Get'][COLLECTION_NAME]:
            articles = result['data']['Get'][COLLECTION_NAME]
            print(f"   ✅ Found {len(articles)} recent articles")
            
            # Sort by publication date
            from datetime import datetime
            for article in articles[:3]:
                pub_date = article.get('publication_date', 'Unknown')
                print(f"   📅 {pub_date[:10]} - {article['title'][:60]}...")
        
        # Test 3: Drug-specific query
        print("\n3️⃣ Drug-Specific Query Test")
        drug_query = "metformin mechanism of action glycemic control"
        embedding = model.encode(drug_query).tolist()
        
        result = client.query \
            .get(COLLECTION_NAME, ['title', 'abstract']) \
            .with_near_vector({'vector': embedding, 'certainty': 0.7}) \
            .with_limit(3) \
            .with_additional(['certainty']) \
            .do()
        
        if result['data']['Get'][COLLECTION_NAME]:
            print(f"   ✅ Found {len(result['data']['Get'][COLLECTION_NAME])} articles on metformin")
            
            # Check for drug mentions in abstracts
            for i, article in enumerate(result['data']['Get'][COLLECTION_NAME], 1):
                abstract_lower = article['abstract'].lower()
                drug_mentions = abstract_lower.count('metformin')
                print(f"   💊 Article {i}: {drug_mentions} mentions of 'metformin'")
        
        print("\n✅ Advanced query tests completed")
        
        return True
        
    except Exception as e:
        print(f"❌ Error in advanced queries: {str(e)}")
        raise

def generate_validation_report(**context):
    """Generate a comprehensive validation report"""
    
    print("\n" + "=" * 60)
    print("📄 GENERATING VALIDATION REPORT")
    print("=" * 60)
    
    try:
        # Retrieve stored results
        health_metrics = json.loads(Variable.get("collection_health_metrics", "{}"))
        search_results = json.loads(Variable.get("semantic_search_results", "[]"))
        search_summary = json.loads(Variable.get("search_summary", "{}"))
        
        # Generate report
        report = {
            'timestamp': datetime.now().isoformat(),
            'collection_status': {
                'name': COLLECTION_NAME,
                'total_documents': health_metrics.get('total_documents', 0),
                'health_check': 'PASSED' if health_metrics.get('total_documents', 0) > 0 else 'FAILED'
            },
            'search_validation': {
                'total_queries_tested': len(search_results),
                'successful_queries': sum(1 for r in search_results if r['results_count'] > 0),
                'average_relevance': search_summary.get('avg_relevance_score', 0),
                'categories_tested': list(set(r['category'] for r in search_results))
            },
            'recommendations': [],
            'overall_status': 'OPERATIONAL'
        }
        
        # Add recommendations based on results
        if health_metrics.get('total_documents', 0) < 10:
            report['recommendations'].append("Consider ingesting more documents for better coverage")
            report['overall_status'] = 'NEEDS_MORE_DATA'
        
        if search_summary.get('avg_relevance_score', 0) < 0.7:
            report['recommendations'].append("Consider using a medical-specific embedding model for better results")
        
        successful_rate = report['search_validation']['successful_queries'] / report['search_validation']['total_queries_tested']
        if successful_rate < 0.8:
            report['recommendations'].append("Some queries returned no results - consider expanding the dataset")
        
        # Print report
        print("\n📊 VALIDATION REPORT SUMMARY")
        print("-" * 40)
        print(f"Status: {report['overall_status']}")
        print(f"Documents: {report['collection_status']['total_documents']}")
        print(f"Query Success Rate: {successful_rate:.1%}")
        print(f"Avg Relevance Score: {report['search_validation']['average_relevance']:.3f}")
        
        if report['recommendations']:
            print("\n💡 Recommendations:")
            for rec in report['recommendations']:
                print(f"   • {rec}")
        
        # Store report
        Variable.set("validation_report", json.dumps(report))
        
        # Create a simple visualization (text-based)
        print("\n📈 Query Performance by Category:")
        if search_results:
            import pandas as pd
            df = pd.DataFrame(search_results)
            category_stats = df.groupby('category').agg({
                'results_count': 'mean',
                'top_score': 'mean'
            }).round(2)
            
            for category, row in category_stats.iterrows():
                bar_length = int(row['top_score'] * 20)  # Scale to 20 chars
                bar = '█' * bar_length + '░' * (20 - bar_length)
                print(f"   {category:15} {bar} {row['top_score']:.2f}")
        
        print("\n✅ Validation report generated successfully!")
        print(f"📁 Report stored in Airflow Variable: 'validation_report'")
        
        return report
        
    except Exception as e:
        print(f"❌ Error generating report: {str(e)}")
        raise

def test_rag_with_llm_simulation(**context):
    """Simulate a RAG pipeline with retrieved documents"""
    import weaviate
    from sentence_transformers import SentenceTransformer
    
    try:
        client = weaviate.Client(url=WEAVIATE_URL)
        model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
        
        print("\n" + "=" * 60)
        print("🤖 TESTING RAG PIPELINE SIMULATION")
        print("=" * 60)
        
        # Simulate a clinical question
        clinical_question = "What is the recommended first-line treatment for newly diagnosed Type 2 diabetes?"
        
        print(f"\n❓ Clinical Question: {clinical_question}")
        
        # Step 1: Retrieve relevant documents
        print("\n1️⃣ Retrieving relevant research...")
        embedding = model.encode(clinical_question).tolist()
        
        result = client.query \
            .get(COLLECTION_NAME, ['title', 'abstract', 'pmid', 'journal']) \
            .with_near_vector({'vector': embedding, 'certainty': 0.7}) \
            .with_limit(3) \
            .with_additional(['certainty']) \
            .do()
        
        if result['data']['Get'][COLLECTION_NAME]:
            articles = result['data']['Get'][COLLECTION_NAME]
            
            print(f"   ✅ Retrieved {len(articles)} relevant articles")
            
            # Step 2: Extract key information
            print("\n2️⃣ Extracting key information...")
            context_pieces = []
            
            for i, article in enumerate(articles, 1):
                print(f"\n   Source {i}:")
                print(f"   Title: {article['title'][:70]}...")
                print(f"   Relevance: {article['_additional']['certainty']:.3f}")
                
                # Extract relevant sentences (simple keyword matching for demo)
                abstract = article['abstract']
                sentences = abstract.split('. ')
                relevant_sentences = [
                    s for s in sentences 
                    if any(kw in s.lower() for kw in ['treatment', 'first-line', 'metformin', 'therapy', 'management'])
                ][:2]  # Take top 2 relevant sentences
                
                if relevant_sentences:
                    context = f"According to {article['journal']} (PMID: {article['pmid']}): {'. '.join(relevant_sentences)}"
                    context_pieces.append(context)
                    print(f"   Extract: {relevant_sentences[0][:100]}...")
            
            # Step 3: Simulate answer generation
            print("\n3️⃣ Generating synthesized answer (simulated)...")
            
            if context_pieces:
                print("\n📝 SIMULATED RAG RESPONSE:")
                print("-" * 40)
                print(f"Based on {len(articles)} recent medical research articles:\n")
                
                # Simulated comprehensive answer
                simulated_answer = f"""
The recommended first-line treatment for newly diagnosed Type 2 diabetes typically includes:

1. **Lifestyle Modifications**: Diet and exercise remain fundamental
2. **Pharmacological Treatment**: Metformin is the preferred initial medication
3. **Monitoring**: Regular HbA1c monitoring every 3-6 months

Evidence from retrieved articles:
{chr(10).join(f'• {ctx[:150]}...' for ctx in context_pieces[:2])}

Note: This is a simulated response. In production, this would be generated by an LLM 
using the retrieved context.
                """
                
                print(simulated_answer)
                
                print("\n📚 References:")
                for i, article in enumerate(articles, 1):
                    print(f"   [{i}] {article['title'][:60]}... (PMID: {article['pmid']})")
            
            return True
        else:
            print("   ❌ No relevant articles found for RAG simulation")
            return False
            
    except Exception as e:
        print(f"❌ Error in RAG simulation: {str(e)}")
        raise

# Create the DAG
with DAG(
    'medical_research_validation',
    default_args=default_args,
    description='Validate medical research data in Weaviate and test RAG queries',
    schedule=None,  # Manual trigger
    catchup=False,
    tags=['healthcare', 'validation', 'testing', 'rag'],
    max_active_runs=1,
) as dag:

    # Task 0: Install packages
    setup_packages = PythonOperator(
        task_id='install_packages',
        python_callable=install_validation_packages,
    )

    # Task 1: Validate collection health
    validate_health = PythonOperator(
        task_id='validate_collection',
        python_callable=validate_collection_health,
    )

    # Task 2: Perform semantic searches
    semantic_search = PythonOperator(
        task_id='semantic_search_tests',
        python_callable=perform_semantic_searches,
    )

    # Task 3: Test advanced queries
    advanced_queries = PythonOperator(
        task_id='advanced_query_tests',
        python_callable=test_advanced_queries,
    )

    # Task 4: Test RAG pipeline
    rag_test = PythonOperator(
        task_id='rag_pipeline_test',
        python_callable=test_rag_with_llm_simulation,
    )

    # Task 5: Generate report
    generate_report = PythonOperator(
        task_id='generate_validation_report',
        python_callable=generate_validation_report,
    )

    # Define task dependencies
    setup_packages >> validate_health >> [semantic_search, advanced_queries] >> rag_test >> generate_report