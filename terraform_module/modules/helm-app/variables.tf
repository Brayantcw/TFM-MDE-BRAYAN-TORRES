variable "namespace" {
  description = "Kubernetes namespace for the application"
  type        = string
  default     = "default"
}

variable "app_name" {
  description = "Name of the application"
  type        = string
  default     = "nginx-test"
}

variable "chart_version" {
  description = "Version of the Helm chart"
  type        = string
  default     = "15.4.4"
}

variable "replicas" {
  description = "Number of replicas"
  type        = number
  default     = 2
}

variable "service_type" {
  description = "Kubernetes service type"
  type        = string
  default     = "ClusterIP"
}

variable "ingress_enabled" {
  description = "Enable ingress for the application"
  type        = bool
  default     = true
}

