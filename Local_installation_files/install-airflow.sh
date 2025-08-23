#!/usr/bin/env bash
# install-airflow.sh
#
# Apache Airflow installer for Docker-Desktop Kubernetes
# - LocalExecutor
# - hostPath PV/PVCs from ./k8s/
# - real Postgres migrations via built-in env-vars
# - full debug/logging

set -euo pipefail
set -x      # ← turn on tracing

# ─── Colors ───────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m';
YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'

# ─── Configuration ────────────────────────────────────────────────────────
AIRFLOW_NAMESPACE="airflow"
AIRFLOW_RELEASE="airflow"
AIRFLOW_VALUES="values.yaml"

WEAVIATE_NAMESPACE="weaviate"
WEAVIATE_RELEASE="weaviate"
WEAVIATE_VALUES="weaviate-values.yaml"

# ─── Helpers ──────────────────────────────────────────────────────────────
info()    { echo -e "${BLUE}ℹ️  $*${NC}"; }
success() { echo -e "${GREEN}✅ $*${NC}"; }
warn()    { echo -e "${YELLOW}⚠️  $*${NC}"; }
error()   { echo -e "${RED}❌ $*${NC}"; exit 1; }

# ─── 1. Preconditions ─────────────────────────────────────────────────────
info "Checking prerequisites..."
command -v kubectl >/dev/null || error "kubectl not installed"
command -v helm   >/dev/null || error "helm not installed"
kubectl cluster-info >/dev/null || error "K8s cluster not accessible"

if [ "$(kubectl config current-context)" != "docker-desktop" ]; then
  warn "Switching to docker-desktop context"
  kubectl config use-context docker-desktop
fi
success "Prerequisites OK"

# ─── 2. Namespaces & Volumes ─────────────────────────────────────────────
info "Ensuring namespaces exist..."
kubectl create ns "$AIRFLOW_NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -
kubectl create ns "$WEAVIATE_NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -
success "Namespaces ready"


apply_volumes() {
  info "Applying all PVs & PVCs from ./k8s/…"
  if ! kubectl apply -f k8s/; then
    error "Failed to apply PVs/PVCs"
  fi
  success "All PVs & PVCs applied"
}

# **Call** it here:
apply_volumes


# ─── 3. Helm Repos ───────────────────────────────────────────────────────
info "Adding/updating Helm repositories…"
helm repo add apache-airflow https://airflow.apache.org 2>/dev/null || true
helm repo add weaviate https://weaviate.github.io/weaviate-helm 2>/dev/null || true
helm repo update
success "Helm repos ready"

# ─── 4. Install/Upgrade Weaviate ─────────────────────────────────────────
info "Deploying Weaviate release '$WEAVIATE_RELEASE'…"
[ -f "$WEAVIATE_VALUES" ] || error "Weaviate values file '$WEAVIATE_VALUES' not found!"

helm upgrade --install \
  "$WEAVIATE_RELEASE" \
  weaviate/weaviate \
  --namespace "$WEAVIATE_NAMESPACE" \
  --values "./$WEAVIATE_VALUES"

success "Weaviate deployed"

# ─── 5. Install/Upgrade Airflow ────────────────────────────────────────────
info "Deploying Airflow release '$AIRFLOW_RELEASE'…"
[ -f "$AIRFLOW_VALUES" ] || error "Airflow values file '$AIRFLOW_VALUES' not found!"

helm upgrade --install \
  "$AIRFLOW_RELEASE" \
  apache-airflow/airflow \
  --namespace "$AIRFLOW_NAMESPACE" \
  --values "./$AIRFLOW_VALUES"

success "Airflow deployed"

# ─── 6. Wait for Pods ─────────────────────────────────────────────────────
wait_for_pods() {
    local namespace=$1
    local service_name=$2
    local max_attempts=60
    local attempt=0
    
    info "Waiting for $service_name pods to be ready in namespace $namespace..."
    
    while [ $attempt -lt $max_attempts ]; do
        # Get pod status
        local ready_pods
        local total_pods
        ready_pods=$(kubectl get pods -n "$namespace" --no-headers 2>/dev/null | grep -c "Running\|Completed" || echo "0")
        total_pods=$(kubectl get pods -n "$namespace" --no-headers 2>/dev/null | wc -l | tr -d ' ' || echo "0")
        
        if [ "$total_pods" -eq 0 ]; then
            warn "No pods found in namespace $namespace, waiting..."
        elif [ "$ready_pods" -eq "$total_pods" ] && [ "$total_pods" -gt 0 ]; then
            success "$service_name pods are ready ($ready_pods/$total_pods)"
            return 0
        else
            info "$service_name pods status: $ready_pods/$total_pods ready"
        fi
        
        sleep 5
        ((attempt++))
    done
    
    error "Timeout waiting for $service_name pods to be ready"
    kubectl get pods -n "$namespace"
    return 1
}

# Wait for both services
wait_for_pods "$WEAVIATE_NAMESPACE" "Weaviate"
wait_for_pods "$AIRFLOW_NAMESPACE" "Airflow"

success "All pods are Ready"

# ─── 7. Status & Port-Forward ─────────────────────────────────────────────
info "Current resources:"
echo "=== Airflow Namespace ==="
kubectl get pods,svc,pvc -n "$AIRFLOW_NAMESPACE"
echo "=== Weaviate Namespace ==="
kubectl get pods,svc,pvc -n "$WEAVIATE_NAMESPACE"
echo "=== Persistent Volumes ==="
kubectl get pv

cat > port-forward.sh << 'EOF'
#!/usr/bin/env bash
# Multi-service port-forwarding with detached processes
set -e

AIRFLOW_NS="airflow"
WEAVIATE_NS="weaviate"
LOGDIR="./logs"

# Colors for output
RED='\033[0;31m'; GREEN='\033[0;32m'; BLUE='\033[0;34m'; NC='\033[0m'
info() { echo -e "${BLUE}ℹ️  $*${NC}"; }
success() { echo -e "${GREEN}✅ $*${NC}"; }
error() { echo -e "${RED}❌ $*${NC}"; }

# Create logs directory
mkdir -p "$LOGDIR"

# Function to start port-forward in background
start_port_forward() {
    local service=$1
    local namespace=$2
    local local_port=$3
    local remote_port=$4
    local log_file="$LOGDIR/${service}-port-forward.log"
    local pid_file="$LOGDIR/${service}-port-forward.pid"
    
    # Check if already running
    if [[ -f "$pid_file" ]] && kill -0 "$(cat "$pid_file")" 2>/dev/null; then
        info "Port-forward for $service already running (PID: $(cat "$pid_file"))"
        return 0
    fi
    
    info "Starting port-forward: $service ($namespace) → localhost:$local_port"
    kubectl port-forward "svc/$service" "$local_port:$remote_port" -n "$namespace" > "$log_file" 2>&1 &
    local pid=$!
    echo "$pid" > "$pid_file"
    
    # Give it a moment to start
    sleep 2
    
    # Check if it's still running
    if kill -0 "$pid" 2>/dev/null; then
        success "Port-forward started for $service (PID: $pid, Log: $log_file)"
    else
        error "Failed to start port-forward for $service. Check $log_file"
        return 1
    fi
}

# Function to stop all port-forwards
stop_all() {
    info "Stopping all port-forwards..."
    for pid_file in "$LOGDIR"/*-port-forward.pid; do
        [[ -f "$pid_file" ]] || continue
        local pid
        pid=$(cat "$pid_file")
        local service
        service=$(basename "$pid_file" -port-forward.pid)
        
        if kill -0 "$pid" 2>/dev/null; then
            kill "$pid"
            success "Stopped port-forward for $service (PID: $pid)"
        fi
        rm -f "$pid_file"
    done
}

# Function to show status
show_status() {
    info "Port-forward status:"
    for pid_file in "$LOGDIR"/*-port-forward.pid; do
        [[ -f "$pid_file" ]] || continue
        local pid
        pid=$(cat "$pid_file")
        local service
        service=$(basename "$pid_file" -port-forward.pid)
        
        if kill -0 "$pid" 2>/dev/null; then
            echo "  ✅ $service (PID: $pid)"
        else
            echo "  ❌ $service (not running)"
            rm -f "$pid_file"
        fi
    done
    echo
    info "Active port forwards:"
    echo "  - Airflow UI: http://localhost:8080"
    echo "  - Weaviate REST API: http://localhost:9090"
    echo "  - Weaviate gRPC: localhost:50051"
}

# Main logic
case "${1:-start}" in
    start)
        info "Starting all port-forwards in background..."
        
        # Find Airflow API server service (could be webserver or api-server)
        AIRFLOW_SVC=$(kubectl get svc -n $AIRFLOW_NS -o jsonpath='{.items[*].metadata.name}' | tr ' ' '\n' | grep -E '(webserver|api-server)$' | head -n1)
        [[ -n "$AIRFLOW_SVC" ]] || { error "Airflow service not found (looking for webserver or api-server)"; exit 1; }
        
        # Start port-forwards
        start_port_forward "$AIRFLOW_SVC" "$AIRFLOW_NS" "8080" "8080"
        start_port_forward "weaviate" "$WEAVIATE_NS" "9090" "8080"
        start_port_forward "weaviate-grpc" "$WEAVIATE_NS" "50051" "50051"
        
        show_status
        ;;
    stop)
        stop_all
        ;;
    status)
        show_status
        ;;
    restart)
        stop_all
        sleep 2
        $0 start
        ;;
    *)
        echo "Usage: $0 {start|stop|status|restart}"
        echo "  start   - Start all port-forwards in background"
        echo "  stop    - Stop all port-forwards"
        echo "  status  - Show current status"
        echo "  restart - Restart all port-forwards"
        exit 1
        ;;
esac
EOF
chmod +x port-forward.sh
success "Created ./port-forward.sh"

echo
echo -e "${GREEN}Installation complete!${NC}"
echo
echo "Next steps:"
echo "1. Start port-forwarding: ./port-forward.sh start"
echo "2. Access services:"
echo "   - Airflow UI: http://localhost:8080 (admin/admin)"
echo "   - Weaviate REST: http://localhost:9090"
echo "   - Weaviate gRPC: localhost:50051"
echo
echo "Port-forward management:"
echo "   ./port-forward.sh {start|stop|status|restart}"
