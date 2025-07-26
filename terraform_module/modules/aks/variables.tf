variable "resource_group_name" { type = string }
variable "location" { type = string }
variable "dns_prefix" { type = string }
variable "cluster_name" { type = string }
variable "subnet_id" { type = string }
variable "node_vm_size" { type = string }
variable "node_count" { type = number }
variable "os_disk_size_gb" { type = number }

variable "enable_ingress" {
  description = "Enable Application Gateway Ingress Controller"
  type        = bool
  default     = false
}

variable "app_gateway_id" {
  description = "Application Gateway ID for AGIC (required if enable_ingress is true)"
  type        = string
  default     = null
}
