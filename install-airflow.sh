#!/usr/bin/env bash
#
# Airflow Kubernetes Installation Script for Docker Desktop (no volumes)
# Installs Apache Airflow via Helm into your local docker-desktop k8s cluster.
# Uses LocalExecutor with ephemeral emptyDir storage.

set -e

# Colors
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'

# Config
NAMESPACE="airflow"
RELEASE_NAME="airflow"
HELM_CHART="apache-airflow/airflow"
VALUES_FILE="values.yaml"

print_status()  { echo -e "${GREEN}✅ $1${NC}"; }
print_warning() { echo -e "${YELLOW}⚠️  $1${NC}"; }
print_error()   { echo -e "${RED}❌ $1${NC}"; }
print_info()    { echo -e "${BLUE}ℹ️  $1${NC}"; }

check_prerequisites() {
  print_info "Checking prerequisites..."
  command -v kubectl >/dev/null 2>&1 || { print_error "kubectl not found"; exit 1; }
  command -v helm   >/dev/null 2>&1 || { print_error "helm not found";   exit 1; }
  kubectl cluster-info >/dev/null 2>&1 || { print_error "K8s cluster down";   exit 1; }
  if [ "$(kubectl config current-context)" != "docker-desktop" ]; then
    print_warning "Switching to docker-desktop context"
    kubectl config use-context docker-desktop
  fi
  print_status "Prerequisites OK"
}

create_namespace() {
  print_info "Ensuring namespace '$NAMESPACE' exists..."
  kubectl create ns "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -
  print_status "Namespace ready"
}

add_helm_repo() {
  print_info "Adding/updating Airflow Helm repo..."
  helm repo add apache-airflow https://airflow.apache.org 2>/dev/null || true
  helm repo update
  print_status "Helm repo ready"
}

install_airflow() {
  print_info "Installing/upgrading Airflow..."
  [ -f "$VALUES_FILE" ] || { print_error "$VALUES_FILE not found"; exit 1; }
  helm upgrade --install "$RELEASE_NAME" "$HELM_CHART" \
    --namespace "$NAMESPACE" \
    --create-namespace \
    -f "$VALUES_FILE" \
    --wait \
    --timeout=10m
  print_status "Airflow deployed"
}

wait_for_pods() {
  print_info "Waiting for all pods to be Ready..."
  kubectl wait --for=condition=ready pod \
    -l app.kubernetes.io/instance="$RELEASE_NAME" \
    -n "$NAMESPACE" \
    --timeout=300s
  print_status "All pods Ready"
}

show_status() {
  print_info "Resources in '$NAMESPACE':"
  kubectl get pods,svc -n "$NAMESPACE"
}

create_port_forward_script() {
  print_info "Creating port-forward script..."
  cat > port-forward.sh << 'EOF'
#!/usr/bin/env bash
NAMESPACE="airflow"
RELEASE="airflow"

SVC=$(kubectl get svc -n $NAMESPACE \
  -l "app.kubernetes.io/instance=$RELEASE,app.kubernetes.io/component=api-server" \
  -o jsonpath='{.items[0].metadata.name}')
echo "Port-forwarding $SVC → localhost:8080"
kubectl port-forward svc/$SVC 8080:8080 -n $NAMESPACE
EOF
  chmod +x port-forward.sh
  print_status "port-forward.sh created"
}

show_next_steps() {
  echo
  echo -e "${GREEN}🎉 Done!${NC}"
  echo "Run ./port-forward.sh then open http://localhost:8080 (admin/admin)"
}

main() {
  check_prerequisites
  create_namespace
  add_helm_repo
  install_airflow
  wait_for_pods
  show_status
  create_port_forward_script
  show_next_steps
}

main "$@"
