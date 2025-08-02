resource "kubernetes_namespace" "airflow" {
  metadata {
    name = var.namespace
  }
}

resource "kubernetes_secret" "git_ssh_key" {
  count = var.enable_ssh_auth ? 1 : 0

  metadata {
    name      = "airflow-git-ssh-key"
    namespace = kubernetes_namespace.airflow.metadata[0].name
  }
  type = "Opaque"
  data = {
    gitSshKey = var.ssh_private_key
  }
}

resource "kubernetes_secret" "git_ssh_known_hosts" {
  count = var.enable_ssh_auth ? 1 : 0

  metadata {
    name      = "airflow-git-known-hosts"
    namespace = kubernetes_namespace.airflow.metadata[0].name
  }
  type = "Opaque"
  data = {
    known_hosts = var.ssh_known_hosts
  }
}

resource "kubernetes_storage_class" "airflow" {
  metadata {
    name = "airflow-storage"
  }
  storage_provisioner = "file.csi.azure.com"
  reclaim_policy      = "Retain"
  parameters = {
    skuName = "Standard_LRS"
  }
  allow_volume_expansion = true
}

resource "kubernetes_storage_class" "postgresql" {
  metadata {
    name = "postgresql-storage"
  }
  storage_provisioner = "disk.csi.azure.com"
  reclaim_policy      = "Retain"
  parameters = {
    skuName = "Standard_LRS"
  }
  allow_volume_expansion = true
}

resource "kubernetes_persistent_volume_claim" "dags" {
  metadata {
    name      = "airflow-dags"
    namespace = kubernetes_namespace.airflow.metadata[0].name
  }
  spec {
    access_modes       = ["ReadWriteMany"]
    storage_class_name = kubernetes_storage_class.airflow.metadata[0].name
    resources {
      requests = {
        storage = var.dags_storage_size
      }
    }
  }
}

resource "kubernetes_persistent_volume_claim" "logs" {
  metadata {
    name      = "airflow-logs"
    namespace = kubernetes_namespace.airflow.metadata[0].name
  }
  spec {
    access_modes       = ["ReadWriteMany"]
    storage_class_name = kubernetes_storage_class.airflow.metadata[0].name
    resources {
      requests = {
        storage = var.logs_storage_size
      }
    }
  }
}

resource "kubernetes_persistent_volume_claim" "plugins" {
  metadata {
    name      = "airflow-plugins"
    namespace = kubernetes_namespace.airflow.metadata[0].name
  }
  spec {
    access_modes       = ["ReadWriteMany"]
    storage_class_name = kubernetes_storage_class.airflow.metadata[0].name
    resources {
      requests = {
        storage = var.plugins_storage_size
      }
    }
  }
}

resource "helm_release" "airflow" {
  name       = var.release_name
  repository = "https://airflow.apache.org"
  chart      = "airflow"
  version    = var.chart_version
  namespace  = kubernetes_namespace.airflow.metadata[0].name

  values = [
    yamlencode({
      images = {
        airflow = {
          repository = "masterbt77/airflow-custom"
          tag        = "v1.0.1"
          pullPolicy = "IfNotPresent"
        }
      }



      executor = "LocalExecutor"

      createUserJob = {
        useHelmHooks   = false
        applyCustomEnv = false
      }

      migrateDatabaseJob = {
        useHelmHooks   = false
        applyCustomEnv = false
      }

      apiServer = {
        defaultUser = {
          enabled  = true
          username = var.admin_user.username
          password = var.admin_user.password
          email    = var.admin_user.email
        }
      }

      ingress = {
        enabled = false
        web = {
          enabled = false
        }
      }

      dags = {
        persistence = {
          enabled       = var.enable_git_sync ? false : true
          existingClaim = var.enable_git_sync ? null : kubernetes_persistent_volume_claim.dags.metadata[0].name
        }
        gitSync = {
          enabled     = var.enable_ssh_auth
          repo        = var.git_repo_url
          branch      = var.git_branch
          subPath     = var.git_dags_subpath
          depth       = 1
          maxFailures = 0
          env = var.enable_ssh_auth ? [
            {
              name  = "SSH_PRIVATE_KEY"
              value = var.ssh_private_key
            }
          ] : []
        }
      }

      logs = {
        persistence = {
          enabled       = true
          existingClaim = kubernetes_persistent_volume_claim.logs.metadata[0].name
        }
      }

      plugins = {
        persistence = {
          enabled       = true
          existingClaim = kubernetes_persistent_volume_claim.plugins.metadata[0].name
        }
      }

      redis = {
        enabled = false
      }

      flower = {
        enabled = false
      }

      postgresql = {
        enabled = true
        auth = {
          username = "airflow"
          password = "airflow"
          database = "airflow"
        }
        persistence = {
          enabled      = true
          storageClass = kubernetes_storage_class.postgresql.metadata[0].name
          accessModes  = ["ReadWriteOnce"]
          size         = "8Gi"
        }
      }

      resources = {
        limits = {
          cpu    = "1000m"
          memory = "2Gi"
        }
        requests = {
          cpu    = "500m"
          memory = "1Gi"
        }
      }
    })
  ]

  depends_on = [
    kubernetes_namespace.airflow,
    kubernetes_storage_class.airflow,
    kubernetes_storage_class.postgresql,
    kubernetes_persistent_volume_claim.dags,
    kubernetes_persistent_volume_claim.logs,
    kubernetes_persistent_volume_claim.plugins,
    kubernetes_secret.git_ssh_key,
    kubernetes_secret.git_ssh_known_hosts
  ]
}

resource "kubernetes_ingress_v1" "airflow_api" {
  metadata {
    annotations = {
      "kubernetes.io/ingress.class"                     = "azure/application-gateway"
      "appgw.ingress.kubernetes.io/backend-path-prefix" = "/"
    }
    name      = "airflow-api-ingress"
    namespace = kubernetes_namespace.airflow.metadata[0].name
  }
  spec {
    rule {
      http {
        path {
          path      = "/"
          path_type = "Prefix"

          backend {
            service {
              name = "airflow-api-server"

              port {
                number = 8080
              }
            }
          }
        }
      }
    }
  }
  depends_on = [helm_release.airflow]
}