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
NAMESPACE="airflow"
RELEASE="airflow"
CHART="apache-airflow/airflow"
VALUES="values.yaml"

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

# ─── 2. Namespace & Volumes ───────────────────────────────────────────────
info "Ensuring namespace '$NAMESPACE' exists..."
kubectl create ns "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -
success "Namespace ready"

info "Applying PVs (cluster-wide)…"

apply_volumes() {
  print_info "Applying PVs & PVCs from k8s/…"
  kubectl apply -f k8s/ \
    || { print_error "Failed to apply PVs/PVCs"; exit 1; }
  print_status "All PVs & PVCs applied"
}


# ─── 3. Helm Repo ─────────────────────────────────────────────────────────
info "Adding/updating Apache Airflow Helm repo…"
helm repo add apache-airflow https://airflow.apache.org 2>/dev/null || true
helm repo update
success "Helm repo ready"

# ─── 4. Install/Upgrade Airflow ────────────────────────────────────────────
info "Deploying Airflow release '$RELEASE'…"
[ -f "$VALUES" ] || error "Values file '$VALUES' not found!"

# Print the exact command we’re about to run
echo
echo ">> helm upgrade --install $RELEASE $CHART \\"
echo "     -n $NAMESPACE \\"
echo "     -f $VALUES \\"
echo "     --wait --wait-for-jobs --timeout=10m \\"
echo "     --debug"
echo

helm upgrade --install "$RELEASE" "$CHART" \
  -n "$NAMESPACE" \
  -f "$VALUES" \
  --wait \
  --wait-for-jobs \
  --timeout=10m \
  --debug

success "Helm release applied"

# ─── 5. Wait for Pods ─────────────────────────────────────────────────────
info "Waiting for Airflow pods to be ready…"
kubectl wait pod \
  -l app.kubernetes.io/instance="$RELEASE" \
  -n "$NAMESPACE" \
  --for=condition=Ready \
  --timeout=300s

success "All pods are Ready"

# ─── 6. Status & Port-Forward ─────────────────────────────────────────────
info "Current resources in ns/$NAMESPACE:"
kubectl get pods,svc,pvc -n "$NAMESPACE"
kubectl get pv

cat > port-forward.sh << 'EOF'
#!/usr/bin/env bash
set -e
NAMESPACE="airflow"
# find the API Server service
SVC=$(kubectl get svc -n $NAMESPACE -o jsonpath='{.items[*].metadata.name}' \
      | tr ' ' '\n' | grep -E 'api-server$' | head -n1)
echo "Forwarding $SVC → localhost:8080"
kubectl port-forward svc/$SVC 8080:8080 -n $NAMESPACE
EOF
chmod +x port-forward.sh
success "Created ./port-forward.sh"

echo
echo -e "${GREEN}🎉 Installation complete!${NC}"
echo "Run ./port-forward.sh and open http://localhost:8080 (admin/admin)"
