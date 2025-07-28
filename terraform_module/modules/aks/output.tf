output "kube_config_raw" {
  description = "Kubeconfig raw"
  value       = azurerm_kubernetes_cluster.this.kube_config_raw
  sensitive   = true
}

output "kube_config" {
  description = "Kubeconfig"
  value       = azurerm_kubernetes_cluster.this.kube_config
  sensitive   = true
}

output "ingress_application_gateway" {
  description = "Application Gateway configuration for ingress"
  value       = var.enable_ingress ? azurerm_kubernetes_cluster.this.ingress_application_gateway : null
}

output "cluster_identity" {
  description = "AKS cluster managed identity"
  value       = azurerm_kubernetes_cluster.this.identity
}
