#!/usr/bin/env bash
set -e
NAMESPACE="airflow"
# find the API Server service
SVC=$(kubectl get svc -n $NAMESPACE -o jsonpath='{.items[*].metadata.name}' \
      | tr ' ' '\n' | grep -E 'api-server$' | head -n1)
echo "Forwarding $SVC → localhost:8080"
kubectl port-forward svc/$SVC 8080:8080 -n $NAMESPACE
