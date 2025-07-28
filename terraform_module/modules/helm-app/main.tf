resource "helm_release" "nginx_app" {
  name       = var.app_name
  repository = "https://charts.bitnami.com/bitnami"
  chart      = "nginx"
  version    = var.chart_version
  namespace  = var.namespace

  create_namespace = true

  values = [
    yamlencode({
      replicaCount = var.replicas

      service = {
        type = var.service_type
      }

      ingress = {
        enabled          = var.ingress_enabled
        ingressClassName = "azure-application-gateway"
        hostname         = ""
        pathType         = "Prefix"
        path             = "/nginx"
        annotations = {
          "kubernetes.io/ingress.class"                     = "azure/application-gateway"
          "appgw.ingress.kubernetes.io/backend-path-prefix" = "/"
        }
      }

      resources = {
        limits = {
          cpu    = "500m"
          memory = "512Mi"
        }
        requests = {
          cpu    = "250m"
          memory = "256Mi"
        }
      }
    })
  ]

  depends_on = [var.namespace]
}


resource "helm_release" "podinfo_app" {
  name       = "podinfo"
  repository = "https://stefanprodan.github.io/podinfo"
  chart      = "podinfo"
  version    = "6.4.0"
  namespace  = var.namespace

  create_namespace = true

  values = [
    yamlencode({
      replicaCount = 1

      service = {
        type = "ClusterIP"
      }

      ingress = {
        enabled   = var.ingress_enabled
        className = "azure-application-gateway"
        hosts = [
          {
            paths = [
              {
                path     = "/podinfo"
                pathType = "Prefix"
              }
            ]
          }
        ]
        annotations = {
          "kubernetes.io/ingress.class"                     = "azure/application-gateway"
          "appgw.ingress.kubernetes.io/backend-path-prefix" = "/"
        }
      }

      resources = {
        limits = {
          cpu    = "100m"
          memory = "128Mi"
        }
        requests = {
          cpu    = "50m"
          memory = "64Mi"
        }
      }
    })
  ]

  depends_on = [var.namespace]
}

