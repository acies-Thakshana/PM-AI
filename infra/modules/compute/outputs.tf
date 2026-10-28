output "listener_arn" {
  description = "ARN of the load balancer listener (API Gateway forwards to it)."
  value       = aws_lb_listener.http.arn
}

output "alb_dns_name" {
  description = "Internal load balancer DNS name (private, for debugging)."
  value       = aws_lb.backend.dns_name
}

output "cluster_name" {
  description = "ECS cluster name."
  value       = aws_ecs_cluster.backend.name
}

output "service_name" {
  description = "ECS service name."
  value       = aws_ecs_service.backend.name
}

output "backend_log_group_name" {
  description = "CloudWatch log group of the backend container."
  value       = aws_cloudwatch_log_group.backend.name
}
