variable "namespace" {
  description = "Kubernetes namespace for Weaviate deployment"
  type        = string
  default     = "weaviate"
}

variable "release_name" {
  description = "Helm release name for Weaviate"
  type        = string
  default     = "weaviate"
}

variable "chart_version" {
  description = "Version of the Weaviate Helm chart"
  type        = string
  default     = "17.4.5"
}

variable "image_tag" {
  description = "Weaviate Docker image tag"
  type        = string
  default     = "1.31.5"
}

variable "pull_policy" {
  description = "Image pull policy"
  type        = string
  default     = "IfNotPresent"
}

variable "storage_size" {
  description = "Size of persistent storage for Weaviate data"
  type        = string
  default     = "2Gi"
}

variable "service_type" {
  description = "Kubernetes service type"
  type        = string
  default     = "ClusterIP"
}

variable "resource_limits" {
  description = "Resource limits for Weaviate pods"
  type = object({
    cpu    = string
    memory = string
  })
  default = {
    cpu    = "1"
    memory = "2Gi"
  }
}

variable "resource_requests" {
  description = "Resource requests for Weaviate pods"
  type = object({
    cpu    = string
    memory = string
  })
  default = {
    cpu    = "500m"
    memory = "1Gi"
  }
}

variable "enable_anonymous_access" {
  description = "Enable anonymous access to Weaviate"
  type        = bool
  default     = true
}

variable "enable_ingress" {
  description = "Enable ingress for external access to Weaviate"
  type        = bool
  default     = false
}

variable "ingress_path" {
  description = "Path for Weaviate ingress"
  type        = string
  default     = "/weaviate"
}