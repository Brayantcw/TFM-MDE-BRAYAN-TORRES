variable "namespace" {
  description = "Kubernetes namespace for Airflow"
  type        = string
  default     = "airflow"
}

variable "release_name" {
  description = "Helm release name for Airflow"
  type        = string
  default     = "airflow"
}

variable "chart_version" {
  description = "Airflow Helm chart version"
  type        = string
  default     = "1.18.0"
}

variable "custom_image" {
  description = "Custom Airflow Docker image"
  type = object({
    repository = string
    tag        = string
    pullPolicy = string
  })
  default = {
    repository = "masterbt77/airflow-custom"
    tag        = "latest"
    pullPolicy = "IfNotPresent"
  }
}

variable "admin_user" {
  description = "Airflow admin user configuration"
  type = object({
    username = string
    password = string
    email    = string
  })
  default = {
    username = "admin"
    password = "admin"
    email    = "admin@example.com"
  }
}

variable "ingress_enabled" {
  description = "Enable ingress for Airflow UI"
  type        = bool
  default     = true
}


variable "storage_class" {
  description = "Storage class for persistent volumes"
  type        = string
  default     = "default"
}

variable "dags_storage_size" {
  description = "Storage size for DAGs volume"
  type        = string
  default     = "2Gi"
}

variable "logs_storage_size" {
  description = "Storage size for logs volume"
  type        = string
  default     = "5Gi"
}

variable "plugins_storage_size" {
  description = "Storage size for plugins volume"
  type        = string
  default     = "1Gi"
}