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
