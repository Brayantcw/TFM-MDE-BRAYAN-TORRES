resource "kubernetes_namespace" "airflow" {
  metadata {
    name = var.namespace
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
          repository = "apache/airflow"
          pullPolicy = "IfNotPresent"
        }
      }


      extraInitContainers = [
        {
          name    = "install-requirements"
          image   = "apache/airflow"
          command = ["/bin/bash"]
          args = [
            "-c",
            "pip install --no-cache-dir ipython fastembed weaviate-client --constraint https://raw.githubusercontent.com/apache/airflow/constraints-3.0.2/constraints-3.9.txt"
          ]
          volumeMounts = [
            {
              name      = "airflow-home"
              mountPath = "/opt/airflow"
            }
          ]
        }
      ]

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
        enabled = var.ingress_enabled
        web = {
          enabled          = var.ingress_enabled
          ingressClassName = "azure-application-gateway"
          path             = "/airflow"
          pathType         = "Prefix"
          annotations = {
            "kubernetes.io/ingress.class" = "azure/application-gateway"
          }
        }
      }

      dags = {
        persistence = {
          enabled       = true
          existingClaim = kubernetes_persistent_volume_claim.dags.metadata[0].name
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
    kubernetes_persistent_volume_claim.plugins
  ]
}

resource "kubernetes_ingress_v1" "airflow_api" {
  metadata {
    annotations = {
      "kubernetes.io/ingress.class" = "azure/application-gateway"
    }
    name      = "airflow-api-ingress"
    namespace = kubernetes_namespace.airflow.metadata[0].name
  }
  spec {
    rule {
      http {
        path {
          path      = "/airflow"
          path_type = "Prefix"

          backend {
            service {
              name = "${var.release_name}-webserver"

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