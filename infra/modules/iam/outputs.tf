output "execution_role_arn" {
  description = "Execution role ARN. The output waits for the managed-policy attachment, so ECS never starts before the role can pull images."
  value       = local.ecs_execution_role_arn
  depends_on  = [aws_iam_role_policy_attachment.ecs_execution_managed]
}

output "task_role_arn" {
  description = "Task role ARN (the app's identity)."
  value       = local.ecs_task_role_arn
}
