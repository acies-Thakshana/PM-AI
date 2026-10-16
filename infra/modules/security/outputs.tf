output "vpclink_security_group_id" {
  description = "Firewall id for the API Gateway VPC Link."
  value       = local.vpclink_security_group_id
}

output "alb_security_group_id" {
  description = "Firewall id for the internal load balancer."
  value       = local.alb_security_group_id
}

output "ecs_security_group_id" {
  description = "Firewall id for the ECS containers."
  value       = local.ecs_security_group_id
}
