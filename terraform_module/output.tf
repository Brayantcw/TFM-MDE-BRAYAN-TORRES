output "kube_admin_config" {
  description = "Raw kubeconfig for the AKS cluster (admin)"
  value       = module.aks.kube_admin_config
  sensitive   = true
}
