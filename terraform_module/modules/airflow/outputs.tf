output "namespace" {
  description = "Airflow namespace"
  value       = kubernetes_namespace.airflow.metadata[0].name
}

output "release_name" {
  description = "Airflow Helm release name"
  value       = helm_release.airflow.name
}

output "release_status" {
  description = "Airflow Helm release status"
  value       = helm_release.airflow.status
}

output "ingress_host" {
  description = "Airflow UI ingress hostname"
  value       = var.ingress_host
}

output "admin_credentials" {
  description = "Airflow admin user credentials"
  value = {
    username = var.admin_user.username
    password = var.admin_user.password
  }
  sensitive = true
}

output "storage_class_name" {
  description = "Created storage class name"
  value       = kubernetes_storage_class.airflow.metadata[0].name
}

output "persistent_volume_claims" {
  description = "Created PVC names"
  value = {
    dags    = kubernetes_persistent_volume_claim.dags.metadata[0].name
    logs    = kubernetes_persistent_volume_claim.logs.metadata[0].name
    plugins = kubernetes_persistent_volume_claim.plugins.metadata[0].name
  }
}