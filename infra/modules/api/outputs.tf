output "invoke_url" {
  description = "Public API URL (ends with a slash)."
  value       = aws_apigatewayv2_stage.default.invoke_url
}

output "api_id" {
  description = "API Gateway API id."
  value       = aws_apigatewayv2_api.backend.id
}
