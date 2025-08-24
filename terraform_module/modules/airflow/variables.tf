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

variable "enable_git_sync" {
  description = "Enable git sync for DAGs from GitHub repository"
  type        = bool
  default     = false
}

variable "git_repo_url" {
  description = "GitHub repository URL for DAGs synchronization"
  type        = string
  default     = ""
}

variable "git_branch" {
  description = "Git branch to sync DAGs from"
  type        = string
  default     = "main"
}

variable "git_dags_subpath" {
  description = "Subdirectory path within the repository containing DAGs"
  type        = string
  default     = "dags"
}

variable "git_sync_wait" {
  description = "Git sync interval in seconds"
  type        = number
  default     = 60
}

variable "git_sync_timeout" {
  description = "Git sync timeout in seconds"
  type        = number
  default     = 120
}

variable "enable_ssh_auth" {
  description = "Enable SSH authentication for private Git repository"
  type        = bool
  default     = false
}

variable "ssh_private_key" {
  description = "SSH private key content for Git authentication"
  type        = string
  default     = ""
  sensitive   = true
}

variable "ssh_known_hosts" {
  description = "SSH known hosts content for Git authentication"
  type        = string
  default     = "github.com ssh-rsa YOUR_KEY_HERE"
  sensitive   = true