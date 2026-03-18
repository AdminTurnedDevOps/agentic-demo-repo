variable "aws_region" {
  description = "The AWS region to create resources in."
  default     = "us-west-1"
}

variable "cluster_name" {
  description = "The name of the EKS cluster."
  default     = "westcluster01"
}

variable "cluster_version" {
  description = "The Kubernetes version for the EKS cluster."
  default     = "1.33"
}

variable "pub_subnet_id_1" {
  type = string
  default = "subnet-03ef49bd20ceff86c"
}

variable "pub_subnet_id_2" {
  type = string
  default = "subnet-05cf46908d6140d8f"
}