# Medical Research Data Pipeline and RAG System

This repository implements a comprehensive medical research data pipeline that combines Apache Airflow workflow orchestration, Weaviate vector database, and AI-powered retrieval-augmented generation (RAG) to enable advanced medical research and patient similarity analysis.

## Overview

The system provides:
- **Automated Data Ingestion**: PubMed medical research papers and synthetic patient data
- **Vector Database Storage**: Semantic search capabilities using medical-specific embeddings
- **Data Validation Pipeline**: Comprehensive quality checks and performance metrics
- **AI-Powered Query Interface**: Multi-provider LLM support for research questions and patient similarity
- **Cloud-Native Infrastructure**: Kubernetes deployment on Azure with Terraform automation

## Key Features

- **Medical Domain Optimization**: Uses specialized BERT models for medical text understanding
- **Dual Data Collections**: Research papers (PubMed) and patient profiles (synthetic diabetes data)
- **Advanced Search**: Vector, BM25, and hybrid search modes with optional reranking
- **Flexible AI Integration**: Supports OpenAI, Azure OpenAI, and local Ollama models
- **Production Ready**: Full infrastructure automation with monitoring and security considerations

## Quick Start

### Prerequisites

**For Azure Deployment:**
- Azure subscription with contributor access
- [Terraform](https://terraform.io) v1.0+ installed  
- [kubectl](https://kubernetes.io/docs/tasks/tools/) installed
- [Helm](https://helm.sh/docs/intro/install/) v3.0+ installed
- [Azure CLI](https://docs.microsoft.com/en-us/cli/azure/install-azure-cli) installed and authenticated

**For Local Development:**
- Docker Desktop with Kubernetes enabled
- Python 3.8+ for local agent development
- Git for repository access (if using private repos)

**For RAG Agent:**
- LLM API access (OpenAI, Azure OpenAI, or local Ollama)
- Streamlit and required Python packages

### Infrastructure Deployment

Deploy the complete infrastructure on Azure:

```bash
# Clone the repository
git clone <repository-url>
cd tfm/terraform_module

# Initialize Terraform (first time only)
terraform init

# Review planned changes
terraform plan

# Deploy infrastructure
terraform apply

# Get AKS credentials
az aks get-credentials --resource-group tfm-brayanto --name aks-cluster
```

This will create:
1. Azure Kubernetes Service (AKS) cluster
2. Apache Airflow with custom medical research DAGs
3. Weaviate vector database for medical document storage
4. Helm charts for service orchestration
5. Application Gateway for secure access

### Local Installation (Development)

For local development with Docker Desktop Kubernetes:

```bash
# Navigate to installation directory
cd Local_installation_files

# Run the automated installation script
./install-airflow.sh
```

**What the script does:**
1. **Prerequisites Check**: Verifies kubectl, helm, and Kubernetes cluster access
2. **Namespace Setup**: Creates `airflow` and `weaviate` namespaces
3. **Storage Preparation**: Applies Kubernetes PV/PVC configurations from `k8s/` directory
4. **Helm Repositories**: Adds Apache Airflow and Weaviate Helm repositories
5. **Service Deployment**: 
   - Installs Weaviate vector database using `weaviate-values.yaml`
   - Installs Apache Airflow using `values.yaml`
6. **Health Verification**: Waits for all pods to be ready (up to 5 minutes per service)
7. **Port-Forward Script**: Generates intelligent `port-forward.sh` script for service access

**Requirements:**
- Docker Desktop with Kubernetes enabled
- kubectl configured for `docker-desktop` context
- Helm 3.0+ installed
- At least 4GB available RAM for the services

### Service Access

**Automated Port-Forwarding (Local Development):**

The installation script creates an intelligent `port-forward.sh` script that manages all service access:

```bash
# Start all port-forwards in background (recommended)
./port-forward.sh start

# Check current status
./port-forward.sh status

# Stop all port-forwards
./port-forward.sh stop

# Restart all services
./port-forward.sh restart
```

**Service Endpoints:**
- **Airflow Web UI**: http://localhost:8080 
  - Credentials: `admin/admin`
  - Automatically detects `airflow-webserver` or `airflow-api-server` services
- **Weaviate REST API**: http://localhost:9090
  - Vector database queries and schema management
- **Weaviate gRPC**: localhost:50051
  - High-performance client connections
- **Medical RAG Agent**: http://localhost:8501 (after running `streamlit run agent.py`)

**Azure Deployment Access:**
- **Airflow UI**: Through Application Gateway (when `enable_app_gateway = true`)
- **Weaviate**: Internal cluster access via kubectl port-forward
- **Services**: Use the same port-forward.sh script with proper kubectl context

**Port-Forward Features:**
- **Detached Operation**: All processes run in background, no terminal blocking
- **Process Management**: Automatic PID tracking and cleanup
- **Health Monitoring**: Detects and restarts failed connections
- **Logging**: Individual log files in `./logs/` directory for debugging
- **Smart Detection**: Automatically finds correct service names

## Local Development Workflow

### Complete Setup Process

1. **Initial Installation:**
   ```bash
   cd Local_installation_files
   ./install-airflow.sh
   ```

2. **Start Services:**
   ```bash
   ./port-forward.sh start
   ```

3. **Verify Installation:**
   ```bash
   ./port-forward.sh status
   ```
   Should show all three services running with PIDs.

4. **Access Services:**
   - Open http://localhost:8080 for Airflow UI (admin/admin)
   - Open http://localhost:9090 for Weaviate Console
   - Test gRPC connection to localhost:50051 from your applications

### Development Commands

**Service Management:**
```bash
./port-forward.sh restart    # Restart all port-forwards
./port-forward.sh stop       # Stop all port-forwards
kubectl get pods -A          # Check pod status across all namespaces
```

**Debugging and Logs:**
```bash
# View port-forward logs
ls -la logs/                 # List all log files
tail -f logs/weaviate-port-forward.log    # Watch Weaviate connection logs

# Check service health
kubectl get pods -n airflow
kubectl get pods -n weaviate

# View application logs
kubectl logs deployment/airflow-scheduler -n airflow
kubectl logs deployment/weaviate -n weaviate
```

**Data Pipeline Operations:**
```bash
# Trigger DAGs (requires port-forwarding active)
# Access Airflow UI at localhost:8080, then trigger:
# - medical_research_ingestion_v2
# - synthetic_patient_data_ingestion_v2  
# - medical_research_validation_v2
# - synthetic_patient_data_validation_v1
```

### Troubleshooting Local Installation

**Common Issues:**

1. **Port-forward fails to start:**
   ```bash
   # Check if ports are already in use
   netstat -an | grep -E "(8080|9090|50051)"
   
   # Kill processes using the ports
   lsof -ti:8080 | xargs kill -9
   ./port-forward.sh start
   ```

2. **Services not ready:**
   ```bash
   # Check pod status
   kubectl get pods -n airflow -w
   kubectl get pods -n weaviate -w
   
   # Check events for issues
   kubectl get events -n airflow --sort-by='.lastTimestamp'
   ```

3. **Installation script fails:**
   ```bash
   # Verify Docker Desktop Kubernetes is running
   kubectl cluster-info
   
   # Check Helm
   helm version
   
   # Re-run with verbose output
   set -x
   ./install-airflow.sh
   ```

---

## Project Structure

```
tfm/
├── dags/                          # Airflow DAG files
│   ├── medical_research_ingestion_v2.py        # PubMed medical research ingestion
│   ├── medical_research_validation_v2.py       # Medical research data validation
│   ├── synthetic_patient_data_ingestion_v2.py  # Synthetic patient data generation
│   └── synthetic_patient_data_validation_v1.py # Patient data validation and quality checks
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
│   ├── k8s/                      # Kubernetes manifests (PV/PVC configs)
│   └── port-forward.sh           # Automated port-forwarding with background processes
├── docker_image/                 # Custom Airflow Docker image
│   ├── dockerfile                # Dockerfile for Airflow with medical packages
│   └── requirements.txt          # Python dependencies (fastembed, weaviate-client, etc.)
├── Utilities/                    # Analysis and utility tools
│   └── plotter.ipynb            # Jupyter notebook for data visualization
├── media/                        # Project documentation assets
│   └── Arquitectura.png         # Architecture diagram
└── README.md                     # This file
```

## Medical Data Pipeline Workflow

This system provides an end-to-end medical research data pipeline:

### 1. Medical Research Ingestion (`medical_research_ingestion_v2.py`)
- **PubMed Integration**: Fetches medical research papers using Biopython
- **Medical Embeddings**: Uses specialized medical BERT models (`pritamdeka/S-PubMedBert-MS-MARCO`)
- **Structured Storage**: Stores papers in Weaviate with metadata (PMID, authors, journal, MeSH terms)
- **Automated Processing**: Handles abstract extraction, keyword processing, and citation analysis

### 2. Synthetic Patient Data Ingestion (`synthetic_patient_data_ingestion_v2.py`)
- **Patient Profiles**: Generates realistic diabetes patient records
- **Clinical Parameters**: HbA1c levels, glucose readings, BMI, blood pressure, eGFR, creatinine
- **Treatment History**: Medication records, complications, lifestyle factors
- **Vector Storage**: Embeds patient profiles for similarity matching using clinical summaries

### 3. Medical Research Validation (`medical_research_validation_v2.py`)
- **Collection Health Checks**: Validates MedicalResearch collection integrity
- **Quality Metrics**: Document count, embedding quality, retrieval accuracy
- **Search Performance**: Tests vector and hybrid search capabilities
- **RAG Pipeline Testing**: End-to-end medical research retrieval validation

### 4. Patient Data Validation (`synthetic_patient_data_validation_v1.py`)
- **Cohort Statistics**: Analyzes patient demographics, clinical metrics, and risk factors
- **Similarity Search**: Tests patient matching and retrieval algorithms
- **Clinical Correlations**: HbA1c-glucose and creatinine-eGFR correlations
- **Data Quality Reports**: Comprehensive validation metrics and recommendations

### 5. AI-Powered Query Interface (`Agent/agent.py`)
- **Medical RAG System**: Retrieval-Augmented Generation for medical questions
- **Dual Collections**: Query both medical research papers and patient data
- **Multiple LLM Providers**: Supports OpenAI, Azure OpenAI, and Ollama
- **Advanced Search**: Vector, BM25, and hybrid search modes with optional reranking
- **Patient Similarity**: Find similar patients based on clinical profiles and filters
- **Streamlit UI**: Interactive web interface for researchers and clinicians

## Technical Architecture

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
- **MedicalResearch Collection**: PubMed papers with clinical metadata (PMID, title, abstract, journal, authors)
- **DiabetesPatients Collection**: Synthetic patient profiles for similarity matching with clinical parameters
- **Embedding Models**: Medical BERT (`pritamdeka/S-PubMedBert-MS-MARCO`) for domain-specific understanding
- **Custom Docker Image**: Extends Apache Airflow with medical data processing libraries (biopython, sentence-transformers, weaviate-client)

## Configuration

### Terraform Variables

Key configuration options in `terraform_module/variables.tf`:

- `resource_group_name`: Azure resource group name (default: "tfm-brayanto")
- `location`: Azure region (default: "eastus")  
- `node_vm_size`: AKS node VM size (default: "Standard_B4ms")
- `node_count`: Number of AKS nodes (default: 2)
- `deploy_weaviate`: Deploy Weaviate database (default: true)
- `enable_app_gateway`: Enable Application Gateway (default: false)
- `ssh_private_key`: SSH key for private Git repos (sensitive)

### Environment Variables

**Airflow DAGs Configuration:**
- `WEAVIATE_URL`: Weaviate endpoint (default: cluster-internal)
- `WEAVIATE_API_KEY`: Optional authentication key

**RAG Agent Configuration:**
- `WEAVIATE_URL`: Weaviate connection URL
- `WEAVIATE_GRPC_PORT`: gRPC port (default: 50051)
- `EMBEDDING_MODEL`: Medical embedding model
- LLM provider keys (OPENAI_API_KEY, AZURE_OPENAI_*, OLLAMA_URL)

## Getting Started with the Medical RAG System

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
- Access Airflow UI and trigger `medical_research_ingestion_v2` DAG
- Run `synthetic_patient_data_ingestion_v2` for patient data
- Execute `medical_research_validation_v2` and `synthetic_patient_data_validation_v1` for quality checks

### 4. Start RAG Agent
```bash
cd Agent

# Install Python dependencies
pip install streamlit weaviate-client sentence-transformers openai

# Set environment variables (choose your LLM provider)
export WEAVIATE_URL="http://localhost:9090"
export OPENAI_API_KEY="your-openai-key"
# OR for Azure OpenAI:
# export AZURE_OPENAI_API_KEY="your-azure-key"
# export AZURE_OPENAI_ENDPOINT="https://your-endpoint.openai.azure.com/"
# OR for local Ollama:
# export OLLAMA_URL="http://localhost:11434"

# Start the Streamlit application
streamlit run agent.py
```

## Troubleshooting

### Common Issues

**DAG Import Errors:**
- Check Python package installations in Airflow pods
- Verify custom Docker image is being used
- Check logs: `kubectl logs deployment/airflow-scheduler -n airflow`

**Weaviate Connection Issues:**
- Verify service discovery and network policies
- Check Weaviate pod status: `kubectl get pods -n weaviate`
- Test connection: `curl http://localhost:9090/v1/meta` (via port-forward)

**Memory and Resource Issues:**
- Adjust resource limits in Helm values files
- Monitor resource usage: `kubectl top pods -n airflow`
- Scale AKS nodes if needed

**Embedding Model Loading:**
- Ensure sufficient disk space for model downloads (2GB+ for medical BERT)
- Check pod startup logs for download progress
- Consider pre-caching models in custom Docker image

**Git Sync Issues (Private Repos):**
- Verify SSH private key is correctly configured
- Check known_hosts configuration in Terraform
- Monitor git-sync container logs

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

## Documentation and Resources

### Medical AI and NLP
- [PubMed API Documentation](https://www.ncbi.nlm.nih.gov/books/NBK25501/)
- [Medical BERT Models](https://huggingface.co/pritamdeka/S-PubMedBert-MS-MARCO)
- [Weaviate Vector Database](https://weaviate.io/developers/weaviate)

### Infrastructure and DevOps
- [Terraform Azure Provider](https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs)
- [Airflow Kubernetes Operator](https://airflow.apache.org/docs/apache-airflow-providers-kubernetes/stable/)
- [Helm Chart Best Practices](https://helm.sh/docs/chart_best_practices/)

## Services and Components

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

## Useful Commands

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
  airflow dags trigger medical_research_ingestion_v2

# Trigger patient data ingestion
kubectl exec -it deployment/airflow-webserver -n airflow -- \
  airflow dags trigger synthetic_patient_data_ingestion_v2

# Monitor DAG runs
kubectl logs -f deployment/airflow-scheduler -n airflow
```

### Weaviate Operations
```bash
# Use automated port-forwarding (recommended)
./port-forward.sh start

# Check collection status
curl http://localhost:9090/v1/schema

# Query medical research
curl -X POST http://localhost:9090/v1/graphql \
  -H "Content-Type: application/json" \
  -d '{"query":"{ Get { MedicalResearch(nearText:{concepts:[\"diabetes\"]}, limit:5) { title abstract } } }"}'

# Manual port-forward (if needed)
kubectl -n weaviate port-forward svc/weaviate 9090:8080
```

## Monitoring and Observability

### Access Points
- **Airflow UI**: https://your-gateway-url/airflow (Azure) or http://localhost:8080 (local via port-forward.sh)
- **Weaviate Console**: http://localhost:9090 (via port-forward)
- **Medical RAG Agent**: http://localhost:8501 (Streamlit)
- **Kubernetes Dashboard**: Available through Azure portal

### Key Metrics to Monitor
- **Data Ingestion Rate**: PubMed articles processed per hour
- **Vector Database Size**: Medical research and patient records stored
- **Query Response Time**: RAG system performance metrics
- **Resource Utilization**: AKS cluster CPU, memory, and storage usage

## Security and Compliance

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

## Medical Use Cases

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