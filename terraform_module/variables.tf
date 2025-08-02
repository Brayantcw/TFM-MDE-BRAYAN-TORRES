variable "resource_group_name" {
  description = "Name of the Azure resource group"
  type        = string
  default     = "tfm-brayanto"
}

variable "location" {
  description = "Azure region"
  type        = string
  default     = "eastus"
}

variable "cluster_name" {
  description = "AKS cluster name"
  type        = string
  default     = "aks-cluster"
}

variable "cluster_prefix" {
  description = "DNS prefix for AKS"
  type        = string
  default     = "aksdns"
}

variable "node_vm_size" {
  description = "Size of the AKS node VMs"
  type        = string
  default     = "Standard_B2s" # Low-cost burstable SKU
}

variable "node_count" {
  description = "Number of nodes in the default pool"
  type        = number
  default     = 2
}

variable "os_disk_size_gb" {
  description = "OS disk size per node"
  type        = number
  default     = 30
}

variable "deploy_validation_apps" {
  description = "Whether to deploy validation helm apps for cluster functionality testing"
  type        = bool
  default     = false
}

variable "deploy_weaviate" {
  description = "Whether to deploy Weaviate vector database"
  type        = bool
  default     = true
}
