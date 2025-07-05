# Apache Airflow on Kubernetes with Helm

This repository is configured to deploy Apache Airflow on a local Kubernetes cluster using the official Helm chart with **hostPath volumes** for seamless local development.

## 🚀 Quick Start

### Prerequisites
- Kubernetes cluster (Docker Desktop, Minikube, k3d, kind, etc.)
- [Helm](https://helm.sh/docs/intro/install/) installed
- [kubectl](https://kubernetes.io/docs/tasks/tools/) installed

### Installation

Simply run the installation script:
```bash
./install-airflow.sh
```

This script will:
1. ✅ Check prerequisites (kubectl, helm, Docker Desktop Kubernetes)
2. ✅ Create namespace and local directories
3. ✅ Create PersistentVolumes and PersistentVolumeClaims using hostPath
4. ✅ Install Airflow with Helm
5. ✅ Create port-forward script
6. ✅ Show you next steps

### Access Airflow

1. **Start port-forwarding:**
   ```bash
   ./port-forward.sh
   ```

2. **Access the Web UI:**
   - URL: http://localhost:8080
   - Username: `admin`
   - Password: `admin`

3. **Access Flower (Celery monitoring):**
   - URL: http://localhost:5555

---

## 📁 Project Structure

```
Master_TFM/
├── dags/                # Your DAG files (automatically synced)
├── plugins/             # Custom plugins (automatically synced)
├── logs/                # Airflow logs (automatically synced)
├── k8s/                 # Kubernetes manifests
│   ├── airflow-local-dags-folder-pv.yaml
│   ├── airflow-local-dags-folder-pvc.yaml
│   ├── airflow-local-plugins-folder-pv.yaml
│   ├── airflow-local-plugins-folder-pvc.yaml
│   ├── airflow-local-logs-folder-pv.yaml
│   └── airflow-local-logs-folder-pvc.yaml
├── values.yaml          # Helm values for Airflow
├── install-airflow.sh   # Installation script
├── port-forward.sh      # Port-forward script (created by installer)
└── README.md            # This file
```

## 🔄 Local Development Workflow

The beauty of this setup is that **your local files are automatically synced** with the Kubernetes pods:

1. **Edit DAGs locally** in `./dags/` - they appear in Airflow immediately
2. **Edit plugins locally** in `./plugins/` - they're available in Airflow
3. **View logs locally** in `./logs/` - all Airflow logs are stored here
4. **No manual copying needed** - just edit and save!

## 🛠️ How It Works

This setup uses **hostPath PersistentVolumes** to mount your local directories directly into the Kubernetes pods:

- `./dags/` → `/opt/airflow/dags/` in Airflow pods
- `./plugins/` → `/opt/airflow/plugins/` in Airflow pods  
- `./logs/` → `/opt/airflow/logs/` in Airflow pods

This approach is based on the excellent guide from [Israeli Tech Radar](https://medium.com/israeli-tech-radar/airflow-on-k8s-for-local-development-5c3ad0ab8e7d).

## 📝 Notes
- For production, use cloud storage backends instead of hostPath
- This setup is optimized for local development with Docker Desktop Kubernetes
- See the [official Helm chart docs](https://airflow.apache.org/docs/helm-chart/stable/index.html) for advanced configuration

## 🐛 Troubleshooting
- If DAGs/plugins don't appear, check the volume mounts and pod logs
- If you need to reset everything:
  ```bash
  helm uninstall airflow -n airflow
  kubectl delete pvc --all -n airflow
  kubectl delete pv airflow-local-dags-folder airflow-local-plugins-folder airflow-local-logs-folder
  ```

## 📚 Resources
- [Airflow Helm Chart Docs](https://airflow.apache.org/docs/helm-chart/stable/index.html)
- [Local Development Guide](https://medium.com/israeli-tech-radar/airflow-on-k8s-for-local-development-5c3ad0ab8e7d)
- [Kubernetes Volumes](https://kubernetes.io/docs/concepts/storage/volumes/)
- [Helm Docs](https://helm.sh/docs/)

## 🔧 Services Included

- **Airflow Webserver** (Port 8080) - Web UI
- **Airflow Scheduler** - Schedules and monitors DAGs
- **Airflow Worker** - Executes tasks
- **Airflow Triggerer** - Handles deferred tasks
- **PostgreSQL** - Metadata database
- **Redis** - Message broker for Celery
- **Flower** (Port 5555) - Celery monitoring tool

## 🛠️ Useful Commands

### Start services
```bash
docker-compose up -d
```

### Stop services
```bash
docker-compose down
```

### View logs
```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f airflow-webserver
```

### Access Airflow CLI
```bash
docker-compose run --rm airflow-cli airflow --help
```

### List DAGs
```bash
docker-compose run --rm airflow-cli airflow dags list
```

### Trigger a DAG
```bash
docker-compose run --rm airflow-cli airflow dags trigger example_dag
```

### Reset everything (⚠️ This will delete all data)
```bash
docker-compose down -v
docker-compose up -d
```

## 📊 Monitoring

- **Airflow Web UI**: http://localhost:8080
- **Flower (Celery monitoring)**: http://localhost:5555

## 🔐 Security

- Default admin credentials are `admin/admin`
- Change these in the `.env` file for production use
- The setup includes basic authentication
- RBAC (Role-Based Access Control) is enabled

## 📝 Adding Your DAGs

1. Place your Python DAG files in the `dags/` directory
2. They will be automatically loaded by Airflow
3. Check the web UI to see your DAGs

## 🔄 Updating Airflow

To update to a newer Airflow version:

1. Update the image version in `values.yaml`