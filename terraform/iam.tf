# iam.tf
# ---------------------------------------------------------------------------
# Modo AWS Academy (use_lab_role = true, PADRAO e caminho testado em aula):
#   - Nao criamos NENHUMA role/policy IAM nova, pois a SCP do Learner Lab
#     bloqueia iam:CreateRole / iam:CreatePolicy / iam:AttachRolePolicy etc.
#   - Em vez disso, localizamos a role "LabRole" (ja existente em toda
#     conta Academy) via data source e reaproveitamos o ARN dela para:
#       1) service role do cluster EKS (eks.tf)
#       2) role do managed node group (eks.tf)
#       3) "role" anotada no service account do ALB Controller
#          (alb-controller.tf) - sem trust policy OIDC/IRSA estrita.
#
# Modo conta real (use_lab_role = false):
#   - Criamos roles e policies IAM dedicadas, seguindo as praticas
#     recomendadas pela AWS (trust policy minima por servico, policies
#     gerenciadas da AWS, e um provider OIDC + IRSA para o ALB Controller).
# ---------------------------------------------------------------------------

# -----------------------------------------------------------------------
# MODO ACADEMY: apenas um lookup (data source) da LabRole ja existente.
# -----------------------------------------------------------------------
data "aws_iam_role" "lab_role" {
  count = var.use_lab_role ? 1 : 0
  name  = var.lab_role_name
}

# -----------------------------------------------------------------------
# MODO CONTA REAL: roles dedicadas (criadas somente se use_lab_role=false)
# -----------------------------------------------------------------------

# Role assumida pelo control plane do EKS.
resource "aws_iam_role" "eks_cluster" {
  count = var.use_lab_role ? 0 : 1
  name  = "${var.project_name}-eks-cluster-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "eks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = local.common_tags
}

resource "aws_iam_role_policy_attachment" "eks_cluster_policy" {
  count      = var.use_lab_role ? 0 : 1
  role       = aws_iam_role.eks_cluster[0].name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSClusterPolicy"
}

# Role assumida pelas instancias EC2 dos worker nodes.
resource "aws_iam_role" "eks_node" {
  count = var.use_lab_role ? 0 : 1
  name  = "${var.project_name}-eks-node-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = local.common_tags
}

resource "aws_iam_role_policy_attachment" "eks_node_worker_policy" {
  count      = var.use_lab_role ? 0 : 1
  role       = aws_iam_role.eks_node[0].name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSWorkerNodePolicy"
}

resource "aws_iam_role_policy_attachment" "eks_node_cni_policy" {
  count      = var.use_lab_role ? 0 : 1
  role       = aws_iam_role.eks_node[0].name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKS_CNI_Policy"
}

resource "aws_iam_role_policy_attachment" "eks_node_ecr_readonly" {
  count      = var.use_lab_role ? 0 : 1
  role       = aws_iam_role.eks_node[0].name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly"
}

resource "aws_iam_role_policy_attachment" "eks_node_ebs_csi" {
  count      = var.use_lab_role ? 0 : 1
  role       = aws_iam_role.eks_node[0].name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonEBSCSIDriverPolicy"
}

resource "aws_iam_instance_profile" "eks_node" {
  count = var.use_lab_role ? 0 : 1
  name  = "${var.project_name}-eks-node-instance-profile"
  role  = aws_iam_role.eks_node[0].name
}

# ---- IRSA (IAM Roles for Service Accounts) para o AWS Load Balancer
# ---- Controller - somente no modo "conta real". No modo Academy isso e
# ---- deliberadamente simplificado (ver alb-controller.tf).

resource "aws_iam_openid_connect_provider" "eks" {
  count = var.use_lab_role ? 0 : 1

  url             = aws_eks_cluster.this.identity[0].oidc[0].issuer
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = ["9e99a48a9960b14926bb7f3b02e22da2b0ab7280"]

  tags = local.common_tags
}

resource "aws_iam_role" "alb_controller_irsa" {
  count = var.use_lab_role ? 0 : 1
  name  = "${var.project_name}-alb-controller-irsa"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Federated = aws_iam_openid_connect_provider.eks[0].arn
      }
      Action = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "${replace(aws_iam_openid_connect_provider.eks[0].url, "https://", "")}:sub" = "system:serviceaccount:kube-system:aws-load-balancer-controller"
          "${replace(aws_iam_openid_connect_provider.eks[0].url, "https://", "")}:aud" = "sts.amazonaws.com"
        }
      }
    }]
  })

  tags = local.common_tags
}

# Policy minima (resumida) para o ALB Controller. Para producao, use a
# policy IAM oficial publicada pelo projeto aws-load-balancer-controller:
# https://raw.githubusercontent.com/kubernetes-sigs/aws-load-balancer-controller/main/docs/install/iam_policy.json
resource "aws_iam_policy" "alb_controller" {
  count       = var.use_lab_role ? 0 : 1
  name        = "${var.project_name}-alb-controller-policy"
  description = "Permissoes para o AWS Load Balancer Controller gerenciar ALBs/NLBs a partir de Ingress/Service do Kubernetes."

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "ec2:DescribeAccountAttributes",
          "ec2:DescribeAddresses",
          "ec2:DescribeInstances",
          "ec2:DescribeSecurityGroups",
          "ec2:DescribeSubnets",
          "ec2:DescribeVpcs",
          "ec2:DescribeTags",
          "ec2:CreateSecurityGroup",
          "ec2:AuthorizeSecurityGroupIngress",
          "ec2:RevokeSecurityGroupIngress",
          "ec2:CreateTags",
          "ec2:DeleteTags",
          "elasticloadbalancing:*",
          "acm:DescribeCertificate",
          "acm:ListCertificates",
          "iam:CreateServiceLinkedRole",
          "shield:GetSubscriptionState",
          "waf-regional:GetWebACL",
          "wafv2:GetWebACL"
        ]
        Resource = "*"
      }
    ]
  })

  tags = local.common_tags
}

resource "aws_iam_role_policy_attachment" "alb_controller" {
  count      = var.use_lab_role ? 0 : 1
  role       = aws_iam_role.alb_controller_irsa[0].name
  policy_arn = aws_iam_policy.alb_controller[0].arn
}

# -----------------------------------------------------------------------
# Locals que escolhem, de forma transparente para o resto do modulo, qual
# ARN de role usar dependendo de use_lab_role. Assim eks.tf e
# alb-controller.tf nao precisam repetir a logica condicional.
# -----------------------------------------------------------------------
locals {
  eks_cluster_role_arn = var.use_lab_role ? data.aws_iam_role.lab_role[0].arn : aws_iam_role.eks_cluster[0].arn
  eks_node_role_arn    = var.use_lab_role ? data.aws_iam_role.lab_role[0].arn : aws_iam_role.eks_node[0].arn

  # No modo Academy a "role" do ALB Controller e, na pratica, a propria
  # LabRole (sem trust policy OIDC dedicada - ver comentario em
  # alb-controller.tf). No modo conta real, usamos a role IRSA criada acima.
  alb_controller_role_arn = var.use_lab_role ? data.aws_iam_role.lab_role[0].arn : aws_iam_role.alb_controller_irsa[0].arn
}
