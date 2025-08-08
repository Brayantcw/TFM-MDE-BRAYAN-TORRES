# Medical Research Ingestion DAG - Corrected Version
import subprocess
import sys
from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.models import Variable
import json
import os
import time
import hashlib
from typing import Dict, List, Any

def install_packages():
    """Install required packages at runtime"""
    packages = ['biopython==1.81', 'sentence-transformers==2.2.2']
    for package in packages:
        try:
            subprocess.check_call([sys.executable, '-m', 'pip', 'install', package])
            print(f"✅ Installed {package}")
        except Exception as e:
            print(f"⚠️ Failed to install {package}: {str(e)}")

# Configuration
WEAVIATE_URL = os.getenv("WEAVIATE_URL", "http://weaviate.weaviate.svc.cluster.local:8080")
ENTREZ_EMAIL = "ba.torres@uniandes.edu.co"  # Fixed email domain

# Use a medical-specific embedding model
EMBEDDING_MODEL = "pritamdeka/S-PubMedBert-MS-MARCO"  # Optimized for medical text
# Alternative: "microsoft/BiomedNLP-PubMedBERT-base-uncased-abstract"

# Collection schema for medical research
MEDICAL_RESEARCH_SCHEMA = {
    "class": "MedicalResearch",
    "description": "Medical research papers and clinical studies",
    "vectorizer": "none",
    "properties": [
        {"name": "pmid", "dataType": ["text"], "description": "PubMed ID"},
        {"name": "title", "dataType": ["text"], "description": "Article title"},
        {"name": "abstract", "dataType": ["text"], "description": "Article abstract"},
        {"name": "authors", "dataType": ["text[]"], "description": "List of authors"},
        {"name": "journal", "dataType": ["text"], "description": "Journal name"},
        {"name": "publication_date", "dataType": ["date"], "description": "Publication date"},
        {"name": "mesh_terms", "dataType": ["text[]"], "description": "MeSH terms"},
        {"name": "keywords", "dataType": ["text[]"], "description": "Keywords"},
        {"name": "doi", "dataType": ["text"], "description": "Digital Object Identifier"},
        {"name": "article_type", "dataType": ["text"], "description": "Type of article"},
        {"name": "citations_count", "dataType": ["int"], "description": "Number of citations"},
        {"name": "condition_focus", "dataType": ["text"], "description": "Primary condition studied"},
        {"name": "study_type", "dataType": ["text"], "description": "Type of study"},
        {"name": "sample_size", "dataType": ["int"], "description": "Study sample size if applicable"},
        {"name": "data_hash", "dataType": ["text"], "description": "Hash for deduplication"},
        {"name": "embedding_model", "dataType": ["text"], "description": "Model used for embedding"},
        {"name": "ingestion_timestamp", "dataType": ["date"], "description": "When data was ingested"}
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
    # Install packages
    install_packages()
    
    # Now import them
    global Entrez, SentenceTransformer, weaviate
    
    try:
        from Bio import Entrez
        print("✅ Biopython imported successfully")
    except ImportError as e:
        print(f"❌ Failed to import Biopython: {str(e)}")
        raise
    
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

def initialize_weaviate_collection():
    """Create the MedicalResearch collection in Weaviate if it doesn't exist"""
    try:
        import weaviate
        client = weaviate.Client(url=WEAVIATE_URL)
        
        # Check if collection exists
        schema = client.schema.get()
        existing_classes = [c['class'] for c in schema.get('classes', [])]
        
        if MEDICAL_RESEARCH_SCHEMA['class'] not in existing_classes:
            client.schema.create_class(MEDICAL_RESEARCH_SCHEMA)
            print(f"✅ Created collection: {MEDICAL_RESEARCH_SCHEMA['class']}")
        else:
            print(f"ℹ️ Collection {MEDICAL_RESEARCH_SCHEMA['class']} already exists")
        
        # Get collection info
        try:
            collection_info = client.query.aggregate(MEDICAL_RESEARCH_SCHEMA['class']) \
                .with_meta_count() \
                .do()
            
            current_count = collection_info['data']['Aggregate'][MEDICAL_RESEARCH_SCHEMA['class']][0]['meta']['count']
            print(f"📊 Current documents in collection: {current_count}")
        except:
            print("📊 Collection is empty or new")
        
        return True
        
    except Exception as e:
        print(f"❌ Error initializing Weaviate: {str(e)}")
        raise

def fetch_pubmed_articles(**context):
    """
    Fetch medical research articles from PubMed
    We'll start with diabetes research as it's well-documented and relevant
    """
    # Import here after installation
    from Bio import Entrez
    
    Entrez.email = ENTREZ_EMAIL
    
    # Get parameters from DAG run or use defaults
    params = context.get('params', {})
    search_query = params.get('search_query', 'diabetes[MeSH] AND ("2023"[Date - Publication] : "2024"[Date - Publication])')
    max_results = params.get('max_results', 10)  # Start with 10 for testing
    
    print(f"🔍 Searching PubMed for: {search_query}")
    print(f"📄 Max results: {max_results}")
    print(f"📧 Using email: {ENTREZ_EMAIL}")
    
    articles = []
    
    try:
        # Search PubMed
        search_handle = Entrez.esearch(
            db="pubmed",
            term=search_query,
            retmax=max_results,
            sort="relevance",
            retmode="xml"
        )
        search_results = Entrez.read(search_handle)
        search_handle.close()
        
        id_list = search_results["IdList"]
        print(f"📋 Found {len(id_list)} articles")
        
        if not id_list:
            print("⚠️ No articles found")
            return []
        
        # Fetch article details in batches
        batch_size = 5  # Smaller batch size for testing
        for i in range(0, len(id_list), batch_size):
            batch_ids = id_list[i:i+batch_size]
            print(f"📥 Fetching batch {i//batch_size + 1}/{(len(id_list)-1)//batch_size + 1}")
            
            fetch_handle = Entrez.efetch(
                db="pubmed",
                id=batch_ids,
                rettype="medline",
                retmode="xml"
            )
            
            fetch_results = Entrez.read(fetch_handle)
            fetch_handle.close()
            
            # Parse articles
            for article in fetch_results['PubmedArticle']:
                try:
                    parsed_article = parse_pubmed_article(article)
                    if parsed_article:
                        articles.append(parsed_article)
                        print(f"   ✓ Parsed: {parsed_article['title'][:50]}...")
                except Exception as e:
                    print(f"   ⚠️ Error parsing article: {str(e)}")
                    continue
            
            # Be respectful to NCBI servers
            time.sleep(0.5)
        
        print(f"✅ Successfully fetched {len(articles)} articles")
        
        # Store in XCom for next task
        return articles
        
    except Exception as e:
        print(f"❌ Error fetching from PubMed: {str(e)}")
        raise

def parse_pubmed_article(article) -> Dict:
    """Parse a PubMed article into our schema format"""
    try:
        medline = article['MedlineCitation']
        article_data = medline['Article']
        
        # Extract PMID
        pmid = str(medline['PMID'])
        
        # Extract title
        title = article_data.get('ArticleTitle', '')
        
        # Extract abstract
        abstract_texts = []
        if 'Abstract' in article_data:
            abstract_sections = article_data['Abstract'].get('AbstractText', [])
            for section in abstract_sections:
                if hasattr(section, 'attributes') and 'Label' in section.attributes:
                    abstract_texts.append(f"{section.attributes['Label']}: {str(section)}")
                else:
                    abstract_texts.append(str(section))
        abstract = ' '.join(abstract_texts)
        
        # Skip if no abstract
        if not abstract:
            print(f"   ⚠️ Skipping article {pmid} - no abstract")
            return None
        
        # Extract authors
        authors = []
        if 'AuthorList' in article_data:
            for author in article_data['AuthorList']:
                if 'LastName' in author and 'ForeName' in author:
                    authors.append(f"{author['ForeName']} {author['LastName']}")
        
        # Extract journal
        journal = article_data.get('Journal', {}).get('Title', '')
        
        # Extract publication date
        pub_date = article_data.get('Journal', {}).get('JournalIssue', {}).get('PubDate', {})
        year = pub_date.get('Year', '2024')
        month = pub_date.get('Month', '01')
        day = pub_date.get('Day', '01')
        
        # Convert month name to number if necessary
        month_map = {'Jan': '01', 'Feb': '02', 'Mar': '03', 'Apr': '04', 'May': '05', 'Jun': '06',
                     'Jul': '07', 'Aug': '08', 'Sep': '09', 'Oct': '10', 'Nov': '11', 'Dec': '12'}
        if month in month_map:
            month = month_map[month]
        elif not month.isdigit():
            month = '01'
        
        publication_date = f"{year}-{month.zfill(2)}-{day.zfill(2)}T00:00:00Z"
        
        # Extract MeSH terms
        mesh_terms = []
        if 'MeshHeadingList' in medline:
            for mesh in medline['MeshHeadingList']:
                if 'DescriptorName' in mesh:
                    mesh_terms.append(str(mesh['DescriptorName']))
        
        # Extract keywords
        keywords = []
        if 'KeywordList' in medline:
            for keyword_list in medline['KeywordList']:
                keywords.extend([str(kw) for kw in keyword_list])
        
        # Extract DOI
        doi = ''
        if 'ELocationID' in article_data:
            for eid in article_data['ELocationID']:
                if eid.attributes.get('EIdType') == 'doi':
                    doi = str(eid)
        
        # Determine article type
        article_types = article_data.get('PublicationTypeList', [])
        article_type = str(article_types[0]) if article_types else 'Research Article'
        
        # Determine study type from article type and abstract
        study_type = classify_study_type(article_type, abstract)
        
        # Extract sample size if mentioned (simple regex approach)
        import re
        sample_size = 0
        sample_match = re.search(r'n\s*=\s*(\d+)', abstract.lower())
        if sample_match:
            sample_size = int(sample_match.group(1))
        
        # Create hash for deduplication
        content_hash = hashlib.md5(f"{pmid}{title}{abstract}".encode()).hexdigest()
        
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
            'citations_count': 0,  # Would need separate API call
            'condition_focus': 'diabetes',  # Based on our search
            'study_type': study_type,
            'sample_size': sample_size,
            'data_hash': content_hash,
            'embedding_model': EMBEDDING_MODEL,
            'ingestion_timestamp': datetime.now().isoformat() + 'Z'
        }
        
    except Exception as e:
        print(f"⚠️ Error parsing article: {str(e)}")
        return None

def classify_study_type(article_type: str, abstract: str) -> str:
    """Classify the type of study based on article type and abstract content"""
    abstract_lower = abstract.lower()
    article_type_lower = article_type.lower()
    
    if 'clinical trial' in article_type_lower or 'randomized' in abstract_lower:
        return 'Clinical Trial'
    elif 'meta-analysis' in article_type_lower or 'meta-analysis' in abstract_lower:
        return 'Meta-Analysis'
    elif 'systematic review' in article_type_lower or 'systematic review' in abstract_lower:
        return 'Systematic Review'
    elif 'case report' in article_type_lower or 'case report' in abstract_lower:
        return 'Case Report'
    elif 'cohort' in abstract_lower or 'prospective' in abstract_lower:
        return 'Cohort Study'
    elif 'cross-sectional' in abstract_lower:
        return 'Cross-Sectional Study'
    else:
        return 'Observational Study'

def generate_embeddings(**context):
    """Generate embeddings for the medical articles"""
    from sentence_transformers import SentenceTransformer
    
    # Get articles from previous task
    ti = context['task_instance']
    articles = ti.xcom_pull(task_ids='fetch_pubmed_articles')
    
    if not articles:
        print("⚠️ No articles to process")
        return []
    
    print(f"🧮 Generating embeddings for {len(articles)} articles")
    print(f"📦 Using embedding model: {EMBEDDING_MODEL}")
    
    # Initialize embedding model
    try:
        model = SentenceTransformer(EMBEDDING_MODEL)
        print("✅ Medical embedding model loaded")
    except Exception as e:
        print(f"⚠️ Error loading medical model: {str(e)}")
        print("🔄 Falling back to general model")
        model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
    
    # Process articles
    articles_with_embeddings = []
    
    for i, article in enumerate(articles):
        try:
            # Create embedding text (title + abstract + keywords)
            embedding_text = f"{article['title']} {article['abstract']}"
            if article['keywords']:
                embedding_text += f" {' '.join(article['keywords'])}"
            if article['mesh_terms']:
                embedding_text += f" {' '.join(article['mesh_terms'])}"
            
            # Truncate if too long (max 512 tokens for most models)
            embedding_text = embedding_text[:2000]
            
            # Generate embedding
            embedding = model.encode(embedding_text).tolist()
            
            # Add embedding to article
            article_with_embedding = {
                **article,
                'embedding': embedding
            }
            
            articles_with_embeddings.append(article_with_embedding)
            
            print(f"📊 Processed {i + 1}/{len(articles)}: {article['title'][:50]}...")
            
        except Exception as e:
            print(f"⚠️ Error processing article {article.get('pmid', 'unknown')}: {str(e)}")
            continue
    
    print(f"✅ Generated embeddings for {len(articles_with_embeddings)} articles")
    
    return articles_with_embeddings

def load_to_weaviate(**context):
    """Load articles with embeddings into Weaviate"""
    import weaviate
    
    # Get articles from previous task
    ti = context['task_instance']
    articles = ti.xcom_pull(task_ids='generate_embeddings')
    
    if not articles:
        print("⚠️ No articles to load")
        return {'loaded': 0, 'skipped': 0, 'failed': 0}
    
    print(f"📤 Loading {len(articles)} articles to Weaviate")
    
    client = weaviate.Client(url=WEAVIATE_URL)
    
    stats = {
        'loaded': 0,
        'skipped': 0,
        'failed': 0
    }
    
    # Check existing articles to avoid duplicates
    existing_pmids = set()
    try:
        result = client.query \
            .get(MEDICAL_RESEARCH_SCHEMA['class'], ['pmid']) \
            .with_limit(10000) \
            .do()
        
        if 'data' in result and 'Get' in result['data']:
            existing_pmids = {
                item['pmid'] 
                for item in result['data']['Get'][MEDICAL_RESEARCH_SCHEMA['class']]
            }
        print(f"📊 Found {len(existing_pmids)} existing articles")
    except Exception as e:
        print(f"⚠️ Could not check existing articles: {str(e)}")
    
    # Load articles
    for article in articles:
        try:
            # Check if already exists
            if article['pmid'] in existing_pmids:
                print(f"⏭️ Skipping duplicate: PMID {article['pmid']}")
                stats['skipped'] += 1
                continue
            
            # Extract embedding
            embedding = article.pop('embedding')
            
            # Create object in Weaviate
            client.data_object.create(
                data_object=article,
                class_name=MEDICAL_RESEARCH_SCHEMA['class'],
                vector=embedding
            )
            
            stats['loaded'] += 1
            print(f"✅ Loaded article {stats['loaded']}: {article['title'][:50]}...")
            
        except Exception as e:
            print(f"❌ Failed to load article {article.get('pmid', 'unknown')}: {str(e)}")
            stats['failed'] += 1
    
    # Final statistics
    print(f"\n📊 LOADING COMPLETE:")
    print(f"   ✅ Loaded: {stats['loaded']}")
    print(f"   ⏭️ Skipped: {stats['skipped']}")
    print(f"   ❌ Failed: {stats['failed']}")
    
    # Store stats
    Variable.set("last_medical_ingestion", json.dumps({
        'timestamp': datetime.now().isoformat(),
        'stats': stats,
        'total_processed': len(articles)
    }))
    
    return stats

# Create the DAG
with DAG(
    'medical_research_ingestion',
    default_args=default_args,
    description='Ingest medical research from PubMed into Weaviate for RAG',
    schedule=None,  # Changed from schedule_interval to schedule for Airflow 3.0
    catchup=False,
    params={
        'search_query': 'diabetes[MeSH] AND ("2023"[Date - Publication] : "2024"[Date - Publication])',
        'max_results': 10  # Start with 10 for testing
    },
    tags=['healthcare', 'pubmed', 'research', 'ingestion'],
    max_active_runs=1,
) as dag:

    # Task 0: Setup dependencies
    setup_deps = PythonOperator(
        task_id='setup_dependencies',
        python_callable=setup_dependencies,
    )

    # Task 1: Initialize Weaviate collection
    init_weaviate = PythonOperator(
        task_id='initialize_weaviate',
        python_callable=initialize_weaviate_collection,
    )

    # Task 2: Fetch articles from PubMed
    fetch_articles = PythonOperator(
        task_id='fetch_pubmed_articles',
        python_callable=fetch_pubmed_articles,
        provide_context=True,
    )

    # Task 3: Generate embeddings
    create_embeddings = PythonOperator(
        task_id='generate_embeddings',
        python_callable=generate_embeddings,
        provide_context=True,
    )

    # Task 4: Load to Weaviate
    load_data = PythonOperator(
        task_id='load_to_weaviate',
        python_callable=load_to_weaviate,
        provide_context=True,
    )
 
    # Define task dependencies
    setup_deps >> init_weaviate >> fetch_articles >> create_embeddings >> load_data