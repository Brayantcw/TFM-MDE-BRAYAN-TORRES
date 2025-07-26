output "nginx_release_name" {
  description = "Name of the nginx Helm release"
  value       = helm_release.nginx_app.name
}

output "nginx_namespace" {
  description = "Namespace of the nginx application"
  value       = helm_release.nginx_app.namespace
}

output "nginx_status" {
  description = "Status of the nginx Helm release"
  value       = helm_release.nginx_app.status
}

output "podinfo_release_name" {
  description = "Name of the podinfo Helm release"
  value       = helm_release.podinfo_app.name
}

output "podinfo_namespace" {
  description = "Namespace of the podinfo application"
  value       = helm_release.podinfo_app.namespace
}

output "podinfo_status" {
  description = "Status of the podinfo Helm release"
  value       = helm_release.podinfo_app.status
}

output "ingress_hosts" {
  description = "List of ingress hosts configured"
  value = [
    var.ingress_host,
    "podinfo.local"
  ]
}