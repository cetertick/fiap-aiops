# eks.tf
# ---------------------------------------------------------------------------
# Cluster EKS e managed node group.
#
# DECISAO DE DESIGN: usamos recursos "crus" (aws_eks_cluster /
# aws_eks_node_group / aws_eks_addon) em vez do modulo
# terraform-aws-modules/eks/aws. O modulo oficial assume, em varios
# pontos internos, que ele mesmo vai criar as IAM roles (ou pelo menos
# fica mais complexo de configurar corretamente para "pular" a criacao de
# roles e IRSA em todos os lugares onde o Academy bloqueia IAM). Usar os
# recursos do provider AWS diretamente deixa o reaproveitamento da
# LabRole (ou das roles dedicadas, no modo conta real) explicito e facil
# de auditar - o que importa mais aqui do que economizar linhas de HCL.
# ---------------------------------------------------------------------------

# Security group adicional para o cluster. O proprio EKS ja cria um SG
# "cluster security group" automaticamente, mas deixamos este SG extra
# para deixar explicito onde regras adicionais (ex.: acesso de ferramentas
# externas) poderiam ser adicionadas durante a aula, se necessario.
resource "aws_security_group" "eks_cluster" {
  name        = "${var.project_name}-eks-cluster-sg"
  description = "Security group adicional do cluster EKS ${local.cluster_name}"
  vpc_id      = module.vpc.vpc_id

  egress {
    description = "Permite todo trafego de saida"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(local.common_tags, {
    Name = "${var.project_name}-eks-cluster-sg"
  })
}

# ---------------------------------------------------------------------------
# Cluster EKS.
# Service role: no modo Academy (use_lab_role=true), e a LabRole
# (local.eks_cluster_role_arn resolve para data.aws_iam_role.lab_role[0].arn
# - ver iam.tf). A LabRole ja tem as permissoes necessarias para o EKS
# gerenciar ENIs, load balancers, etc, mesmo sem a trust policy "oficial"
# do EKS (eks.amazonaws.com) - isso funciona na pratica porque a LabRole
# tem uma trust policy ampla liberada pelo ambiente do Academy.
# ---------------------------------------------------------------------------
resource "aws_eks_cluster" "this" {
  name     = local.cluster_name
  role_arn = local.eks_cluster_role_arn
  version  = var.cluster_version

  vpc_config {
    subnet_ids = concat(module.vpc.public_subnets, module.vpc.private_subnets)

    # Endpoint publico habilitado para simplicidade em sala de aula
    # (kubectl/helm direto da maquina do aluno, sem VPN/bastion).
    endpoint_public_access = true
    # Endpoint privado tambem habilitado, para que os proprios nodes e
    # addons dentro da VPC usem o caminho privado quando possivel.
    endpoint_private_access = true

    security_group_ids = [aws_security_group.eks_cluster.id]
  }

  tags = merge(local.common_tags, {
    Name = local.cluster_name
  })

  # Em modo conta real, o aws_iam_role_policy_attachment precisa existir
  # antes do cluster ser criado; em modo Academy nao ha attachment
  # (LabRole ja tem as policies), entao a lista fica vazia e o depends_on
  # nao faz nada (comportamento esperado).
  depends_on = [
    aws_iam_role_policy_attachment.eks_cluster_policy,
  ]
}

# ---------------------------------------------------------------------------
# Managed Node Group "AIOPS-workers".
# Node role: no modo Academy, tambem a LabRole. Isso e o padrao oficial
# recomendado pela AWS Academy para EKS: usar LabInstanceProfile/LabRole
# tanto para o control plane quanto para os worker nodes.
# ---------------------------------------------------------------------------
resource "aws_eks_node_group" "aiops_workers" {
  cluster_name    = aws_eks_cluster.this.name
  node_group_name = "AIOPS-workers"
  node_role_arn   = local.eks_node_role_arn
  subnet_ids      = module.vpc.private_subnets

  instance_types = [var.node_instance_type]
  capacity_type  = "ON_DEMAND"

  scaling_config {
    desired_size = var.node_desired_size
    min_size     = var.node_min_size
    max_size     = var.node_max_size
  }

  update_config {
    max_unavailable = 1
  }

  # Label aplicada em todos os nodes deste node group, para facilmente
  # identificar/selecionar (nodeSelector, afinidade) os workers da aula
  # AIOps no Kubernetes (`kubectl get nodes -L node-group`).
  labels = {
    "node-group" = "AIOPS"
    "role"       = "AIOPS"
  }

  tags = merge(local.common_tags, {
    Name = "AIOPS-workers"
  })

  depends_on = [
    aws_eks_cluster.this,
    aws_iam_role_policy_attachment.eks_node_worker_policy,
    aws_iam_role_policy_attachment.eks_node_cni_policy,
    aws_iam_role_policy_attachment.eks_node_ecr_readonly,
  ]

  lifecycle {
    ignore_changes = [scaling_config[0].desired_size]
  }
}

# ---------------------------------------------------------------------------
# Addons gerenciados do EKS.
#
# - vpc-cni: rede de pods (ENIs); necessario para qualquer pod rodar.
# - coredns: DNS interno do cluster.
# - kube-proxy: regras de rede/Service (iptables/ipvs) em cada node.
# - aws-ebs-csi-driver: provisionamento dinamico de EBS para PVCs
#   (necessario para Prometheus, Loki e Tempo, que usam armazenamento
#   persistente para metricas/logs/traces).
#
# No modo Academy, o aws-ebs-csi-driver roda usando a propria role dos
# nodes (LabRole) para falar com a API do EBS, em vez de uma role IRSA
# dedicada - simplificacao aceitavel para a aula, ja que a LabRole tem
# permissao de EC2/EBS de sobra.
# ---------------------------------------------------------------------------
resource "aws_eks_addon" "vpc_cni" {
  cluster_name = aws_eks_cluster.this.name
  addon_name   = "vpc-cni"

  resolve_conflicts_on_update = "OVERWRITE"

  depends_on = [aws_eks_node_group.aiops_workers]
}

resource "aws_eks_addon" "coredns" {
  cluster_name = aws_eks_cluster.this.name
  addon_name   = "coredns"

  resolve_conflicts_on_update = "OVERWRITE"

  depends_on = [aws_eks_node_group.aiops_workers]
}

resource "aws_eks_addon" "kube_proxy" {
  cluster_name = aws_eks_cluster.this.name
  addon_name   = "kube-proxy"

  resolve_conflicts_on_update = "OVERWRITE"

  depends_on = [aws_eks_node_group.aiops_workers]
}

resource "aws_eks_addon" "ebs_csi_driver" {
  cluster_name = aws_eks_cluster.this.name
  addon_name   = "aws-ebs-csi-driver"

  resolve_conflicts_on_update = "OVERWRITE"

  # Em modo conta real (use_lab_role=false), o ideal seria criar uma role
  # IRSA dedicada para o EBS CSI driver e referencia-la aqui via
  # `service_account_role_arn`. Deixamos essa role de fora por simplicidade
  # (fora do escopo principal da aula) - em modo Academy, o driver usa a
  # role dos nodes (LabRole), que ja tem permissao de EBS.
  depends_on = [aws_eks_node_group.aiops_workers]
}
