resource "kubernetes_namespace" "weaviate" {
  metadata {
    name = var.namespace
  }
}

resource "helm_release" "weaviate" {
  name       = var.release_name
  repository = "https://weaviate.github.io/weaviate-helm"
  chart      = "weaviate"
  version    = var.chart_version
  namespace  = kubernetes_namespace.weaviate.metadata[0].name

  values = [
    yamlencode({
      image = {
        tag        = var.image_tag
        pullPolicy = var.pull_policy
      }

      storage = {
        size = var.storage_size
      }

      service = {
        type = var.service_type
        ports = [
          {
            name       = "http"
            port       = 8080
            targetPort = 8080
          },
          {
            name       = "grpc"
            port       = 50051
            targetPort = 50051
          }
        ]
      }

      resources = {
        limits = {
          cpu    = var.resource_limits.cpu
          memory = var.resource_limits.memory
        }
        requests = {
          cpu    = var.resource_requests.cpu
          memory = var.resource_requests.memory
        }
      }

      authentication = {
        anonymous_access = {
          enabled = var.enable_anonymous_access
        }
      }

      ingress = {
        enabled          = var.enable_ingress
        ingressClassName = var.enable_ingress ? "azure-application-gateway" : null
        pathType         = var.enable_ingress ? "Prefix" : null
        path             = var.enable_ingress ? var.ingress_path : null
        annotations = var.enable_ingress ? {
          "kubernetes.io/ingress.class"                     = "azure/application-gateway"
          "appgw.ingress.kubernetes.io/backend-path-prefix" = "/"
        } : {}
      }
    })
  ]

  depends_on = [kubernetes_namespace.weaviate]
}