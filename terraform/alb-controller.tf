# alb-controller.tf
# ---------------------------------------------------------------------------
# AWS Load Balancer Controller, instalado via Helm. E esse controller que,
# mais adiante na aula, vai observar recursos Ingress com
# `ingressClassName: alb` (ex.: UI do ArgoCD, APIs de exemplo) e provisionar
# Application Load Balancers reais na AWS automaticamente.
#
# *** SIMPLIFICACAO DE IRSA NO MODO ACADEMY (use_lab_role = true) ***
# O padrao "correto" em produção e usar IRSA (IAM Roles for Service
# Accounts): um provider OIDC no cluster + uma IAM role com trust policy
# que so pode ser assumida pelo service account especifico
# (system:serviceaccount:kube-system:aws-load-balancer-controller).
#
# No AWS Academy isso teria 2 problemas:
#   1) Criar a IAM role com essa trust policy e bloqueado pela SCP (nao
#      podemos criar roles IAM novas).
#   2) Mesmo que pudessemos, a LabRole existente NAO tem uma trust policy
#      que aceite "AssumeRoleWithWebIdentity" vindo do provider OIDC do
#      nosso cluster especifico - e nao podemos editar a trust policy da
#      LabRole (tambem bloqueado).
#
# Por isso, em modo Academy, simplesmente anotamos o ServiceAccount do
# controller com `eks.amazonaws.com/role-arn = <ARN da LabRole>`. Isso NAO
# ativa IRSA de fato (sem OIDC provider, a anotacao e essencialmente
# ignorada pelo STS), e o controller acaba usando as permissoes da role
# dos WORKER NODES (tambem a LabRole, ver eks.tf) para falar com a API da
# AWS - que e ampla o suficiente para criar/gerenciar ALBs. Isso FUNCIONA
# para fins didaticos, mas NAO e a pratica recomendada de seguranca em
# produção (IRSA existe justamente para dar ao controller apenas as
# permissoes de que ele precisa, isoladas da role dos nodes).
#
# No modo conta real (use_lab_role = false), a anotacao aponta para a role
# IRSA dedicada criada em iam.tf (com OIDC provider e trust policy
# corretos), que e a forma recomendada pela AWS.
# ---------------------------------------------------------------------------

resource "helm_release" "aws_load_balancer_controller" {
  name       = "aws-load-balancer-controller"
  repository = "https://aws.github.io/eks-charts"
  chart      = "aws-load-balancer-controller"
  namespace  = "kube-system"

  # Versao do chart compativel com Kubernetes 1.30.
  version = "1.8.1"

  set {
    name  = "clusterName"
    value = aws_eks_cluster.this.name
  }

  set {
    name  = "region"
    value = var.aws_region
  }

  set {
    name  = "vpcId"
    value = module.vpc.vpc_id
  }

  # Cria o ServiceAccount via Helm, ja anotado com o ARN da role (LabRole
  # em modo Academy, ou a role IRSA dedicada em modo conta real - ver
  # explicacao acima).
  set {
    name  = "serviceAccount.create"
    value = "true"
  }

  set {
    name  = "serviceAccount.name"
    value = "aws-load-balancer-controller"
  }

  set {
    name  = "serviceAccount.annotations.eks\\.amazonaws\\.com/role-arn"
    value = local.alb_controller_role_arn
  }

  depends_on = [
    aws_eks_node_group.aiops_workers,
    aws_eks_addon.vpc_cni,
  ]
}
