output "vpc_id" {
  description = "The VPC in use (created here or the client's)."
  value       = local.vpc_id
}

output "private_subnet_ids" {
  description = "Private subnet ids used by the VPC Link, the load balancer and ECS."
  value       = local.private_subnet_ids
}

output "private_route_table_ids" {
  description = "Private route table ids (the gateway endpoints attach here)."
  value       = local.private_route_table_ids
}
