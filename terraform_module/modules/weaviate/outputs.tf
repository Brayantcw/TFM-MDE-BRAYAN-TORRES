output "namespace" {
  description = "Kubernetes namespace where Weaviate is deployed"
  value       = kubernetes_namespace.weaviate.metadata[0].name
}

output "release_name" {
  description = "Helm release name for Weaviate"
  value       = helm_release.weaviate.name
}

output "service_name" {
  description = "Kubernetes service name for Weaviate"
  value       = var.release_name
}

output "http_endpoint" {
  description = "HTTP endpoint for Weaviate API (internal cluster access)"
  value       = "http://${var.release_name}.${kubernetes_namespace.weaviate.metadata[0].name}.svc.cluster.local:8080"
}

output "grpc_endpoint" {
  description = "gRPC endpoint for Weaviate (internal cluster access)"
  value       = "${var.release_name}.${kubernetes_namespace.weaviate.metadata[0].name}.svc.cluster.local:50051"
}

output "http_port" {
  description = "HTTP port for Weaviate service"
  value       = 8080
}

output "grpc_port" {
  description = "gRPC port for Weaviate service"
  value       = 50051
}

output "connection_string" {
  description = "Connection string for applications to connect to Weaviate"
  value       = "http://${var.release_name}.${kubernetes_namespace.weaviate.metadata[0].name}.svc.cluster.local:8080"
}