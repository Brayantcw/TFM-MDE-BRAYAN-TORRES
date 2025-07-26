output "kube_config" {
  description = "Raw kubeconfig for the AKS cluster"
  value       = module.aks.kube_config
  sensitive   = true
}
