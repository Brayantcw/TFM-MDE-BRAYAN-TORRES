# Medical Research Data Pipeline and RAG System

This repository implements a comprehensive medical research data pipeline using Apache Airflow, Weaviate vector database, and AI-powered retrieval-augmented generation (RAG) for medical research and patient similarity analysis.

## 🚀 Quick Start

### Prerequisites
- Azure subscription with AKS cluster access
- [Terraform](https://terraform.io) installed  
- [kubectl](https://kubernetes.io/docs/tasks/tools/) installed
- [Helm](https://helm.sh/docs/intro/install/) installed
- Python 3.8+ for local agent development

### Infrastructure Deployment

Deploy the complete infrastructure on Azure:

```bash
cd terraform_module
terraform init
terraform plan
terraform apply
```

This will create:
1. ✅ Azure Kubernetes Service (AKS) cluster
2. ✅ Apache Airflow with custom medical research DAGs
3. ✅ Weaviate vector database for medical document storage
4. ✅ Helm charts for service orchestration
5. ✅ Application Gateway for secure access

### Local Installation (Development)

For local development with Docker Desktop Kubernetes:
```bash
cd Local_installation_files
./install-airflow.sh
```

### Access Services

1. **Airflow Web UI:**
   - Azure: Through Application Gateway (HTTPS)
   - Local: http://localhost:8080 (after port-forward)
   - Credentials: `admin/admin`

2. **Weaviate Vector Database:**
   - Azure: Internal cluster access
   - Local: http://localhost:9090 (after port-forward)

3. **Medical RAG Agent:**
   ```bash
   cd Agent
   pip install -r requirements.txt
   streamlit run agent.py
   ```

---

## 📁 Project Structure

```
tfm/
├── dags/                          # Airflow DAG files
│   ├── dag_pulling_data.py        # PubMed medical research ingestion
│   ├── dag_data_generator.py      # Synthetic patient data generation  
│   └── dag_validator.py           # Data validation and quality checks
├── Agent/                         # Medical RAG Agent (Streamlit app)
│   └── agent.py                   # Main agent application
├── terraform_module/              # Infrastructure as Code
│   ├── main.tf                    # Main Terraform configuration
│   ├── modules/                   # Terraform modules
│   │   ├── aks/                   # Azure Kubernetes Service
│   │   ├── airflow/              # Airflow deployment
│   │   ├── weaviate/             # Weaviate vector database
│   │   └── helm-app/             # Helm application management
│   └── variables.tf              # Terraform variables
├── Local_installation_files/      # Local development setup
│   ├── install-airflow.sh        # Local Airflow installation
│   ├── values.yaml               # Helm values for Airflow
│   ├── weaviate-values.yaml      # Helm values for Weaviate
│   ├── k8s/                      # Kubernetes manifests
│   └── notebooks/                # Jupyter notebooks for analysis
├── logs/                         # Airflow execution logs
└── README.md                     # This file
```

## 🔄 Medical Data Pipeline Workflow

This system provides an end-to-end medical research data pipeline:

### 1. Data Ingestion (`dag_pulling_data.py`)
- **PubMed Integration**: Fetches medical research papers using Biopython
- **Medical Embeddings**: Uses specialized medical BERT models (`pritamdeka/S-PubMedBert-MS-MARCO`)
- **Structured Storage**: Stores papers in Weaviate with metadata (PMID, authors, journal, MeSH terms)
- **Automated Processing**: Handles abstract extraction, keyword processing, and citation analysis

### 2. Synthetic Data Generation (`dag_data_generator.py`)
- **Patient Profiles**: Generates realistic diabetes patient records
- **Clinical Parameters**: HbA1c levels, glucose readings, BMI, blood pressure
- **Treatment History**: Medication records, complications, lifestyle factors
- **Vector Storage**: Embeds patient profiles for similarity matching

### 3. Data Validation (`dag_validator.py`)
- **Quality Checks**: Validates data integrity and completeness
- **Semantic Search Tests**: Ensures proper embedding and retrieval
- **RAG Pipeline Testing**: End-to-end system validation
- **Performance Metrics**: Query response times and accuracy

### 4. AI-Powered Query Interface
- **Research Assistant**: Ask questions about medical literature
- **Patient Similarity**: Find similar patients based on clinical profiles
- **Vector Search**: Semantic similarity using medical embeddings
- **Streamlit UI**: User-friendly interface for researchers

## 🛠️ Technical Architecture

### Infrastructure Components
- **Azure Kubernetes Service (AKS)**: Container orchestration platform
- **Apache Airflow**: Workflow orchestration and scheduling
- **Weaviate**: Vector database for semantic search and embeddings
- **Terraform**: Infrastructure as Code for reproducible deployments
- **Helm Charts**: Application package management for Kubernetes

### Data Flow Architecture
1. **Ingestion Layer**: PubMed API → Data Processing → Medical Embeddings
2. **Storage Layer**: Weaviate Vector Database with medical-optimized schemas
3. **Processing Layer**: Airflow DAGs for ETL and data validation
4. **Application Layer**: Streamlit-based RAG interface
5. **Infrastructure Layer**: Terraform-managed Azure resources

### Medical Data Models
- **MedicalResearch Collection**: PubMed papers with clinical metadata
- **DiabetesPatients Collection**: Synthetic patient profiles for similarity matching
- **Embedding Models**: Specialized medical BERT variants for domain-specific understanding

## 🚀 Getting Started with the Medical RAG System

### 1. Deploy Infrastructure
```bash
# Deploy to Azure
cd terraform_module
terraform apply

# OR for local development
cd Local_installation_files
./install-airflow.sh
```

### 2. Configure Weaviate
```bash
# Add Weaviate Helm repository
helm repo add weaviate https://weaviate.github.io/weaviate-helm

# Install Weaviate
helm upgrade --install weaviate weaviate/weaviate \
  --namespace weaviate \
  --values Local_installation_files/weaviate-values.yaml
```

### 3. Run Data Pipeline
- Access Airflow UI and trigger `medical_research_ingestion` DAG
- Run `synthetic_patient_data_ingestion` for patient data
- Execute `medical_research_validation` for quality checks

### 4. Start RAG Agent
```bash
cd Agent
streamlit run agent.py
```

## 🐛 Troubleshooting

### Common Issues
- **DAG Import Errors**: Check Python package installations in Airflow pods
- **Weaviate Connection**: Verify service discovery and network policies
- **Memory Issues**: Adjust resource limits in Helm values
- **Embedding Model Loading**: Ensure sufficient disk space for model downloads

### Reset Commands
```bash
# Reset Airflow
helm uninstall airflow -n airflow
kubectl delete namespace airflow

# Reset Weaviate
helm uninstall weaviate -n weaviate  
kubectl delete namespace weaviate

# Reset Terraform (Azure)
terraform destroy
```

## 📚 Documentation and Resources

### Medical AI and NLP
- [PubMed API Documentation](https://www.ncbi.nlm.nih.gov/books/NBK25501/)
- [Medical BERT Models](https://huggingface.co/pritamdeka/S-PubMedBert-MS-MARCO)
- [Weaviate Vector Database](https://weaviate.io/developers/weaviate)

### Infrastructure and DevOps
- [Terraform Azure Provider](https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs)
- [Airflow Kubernetes Operator](https://airflow.apache.org/docs/apache-airflow-providers-kubernetes/stable/)
- [Helm Chart Best Practices](https://helm.sh/docs/chart_best_practices/)

## 🔧 Services and Components

### Core Infrastructure
- **Azure Kubernetes Service (AKS)** - Container orchestration
- **Airflow Webserver** (Port 8080) - Workflow management UI
- **Airflow Scheduler** - DAG scheduling and task orchestration
- **Airflow Workers** - Task execution with medical data processing
- **PostgreSQL** - Airflow metadata database
- **Redis** - Message broker for distributed task processing

### Data and AI Services  
- **Weaviate Vector Database** (Port 8080) - Semantic search and embeddings
- **Medical RAG Agent** (Streamlit) - AI-powered research interface
- **Embedding Models** - Medical BERT for domain-specific understanding
- **PubMed Integration** - Real-time medical literature ingestion

### Monitoring and Management
- **Terraform State Management** - Infrastructure versioning
- **Kubernetes Dashboards** - Cluster monitoring
- **Airflow Logs** - Centralized logging with medical data audit trails
- **Application Gateway** - Secure access and load balancing

## 🛠️ Useful Commands

### Infrastructure Management
```bash
# Deploy complete infrastructure
terraform apply -auto-approve

# Scale AKS cluster
az aks scale --resource-group tfm-rg --name aks-cluster --node-count 3

# Get cluster credentials  
az aks get-credentials --resource-group tfm-rg --name aks-cluster
```

### Airflow Operations
```bash
# List medical research DAGs
kubectl exec -it deployment/airflow-webserver -n airflow -- airflow dags list

# Trigger medical data ingestion
kubectl exec -it deployment/airflow-webserver -n airflow -- \
  airflow dags trigger medical_research_ingestion

# Monitor DAG runs
kubectl logs -f deployment/airflow-scheduler -n airflow
```

### Weaviate Operations
```bash
# Port forward to access Weaviate locally
kubectl -n weaviate port-forward svc/weaviate 9090:8080

# Check collection status
curl http://localhost:9090/v1/schema

# Query medical research
curl -X POST http://localhost:9090/v1/graphql \
  -H "Content-Type: application/json" \
  -d '{"query":"{ Get { MedicalResearch(nearText:{concepts:[\"diabetes\"]}, limit:5) { title abstract } } }"}'
```

## 📊 Monitoring and Observability

### Access Points
- **Airflow UI**: https://your-gateway-url/airflow (Azure) or http://localhost:8080 (local)
- **Weaviate Console**: http://localhost:9090 (via port-forward)
- **Medical RAG Agent**: http://localhost:8501 (Streamlit)
- **Kubernetes Dashboard**: Available through Azure portal

### Key Metrics to Monitor
- **Data Ingestion Rate**: PubMed articles processed per hour
- **Vector Database Size**: Medical research and patient records stored
- **Query Response Time**: RAG system performance metrics
- **Resource Utilization**: AKS cluster CPU, memory, and storage usage

## 🔐 Security and Compliance

### Authentication and Access Control
- **Azure AD Integration**: Role-based access control for AKS
- **Airflow RBAC**: User and role management for workflow access
- **Network Policies**: Kubernetes network segmentation
- **Secret Management**: Azure Key Vault integration for sensitive data

### Medical Data Privacy
- **HIPAA Considerations**: Synthetic patient data for development/testing
- **Data Encryption**: At-rest and in-transit encryption for medical records
- **Access Logging**: Comprehensive audit trails for data access
- **Data Anonymization**: PII removal and clinical data de-identification

## 🧬 Medical Use Cases

### Supported Research Workflows
1. **Literature Review**: Semantic search across PubMed database
2. **Clinical Decision Support**: Patient similarity matching for treatment recommendations  
3. **Drug Discovery**: Research paper analysis for therapeutic insights
4. **Epidemiological Studies**: Population health data analysis and visualization
5. **Clinical Trial Design**: Patient cohort identification and stratification

### Example Queries
```python
# Find similar patients
"Show me patients similar to: 45-year-old male, Type 2 diabetes, HbA1c 8.5%"

# Research questions
"What are the latest treatments for diabetic nephropathy?"

# Clinical insights
"Compare metformin vs insulin effectiveness in elderly patients"
```