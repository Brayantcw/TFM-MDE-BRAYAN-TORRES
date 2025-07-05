#!/usr/bin/env bash
NAMESPACE="airflow"
RELEASE="airflow"

SVC=$(kubectl get svc -n $NAMESPACE \
  -l "app.kubernetes.io/instance=$RELEASE,app.kubernetes.io/component=api-server" \
  -o jsonpath='{.items[0].metadata.name}')
echo "Port-forwarding $SVC → localhost:8080"
kubectl port-forward svc/$SVC 8080:8080 -n $NAMESPACE
