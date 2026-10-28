output "repository_url" {
  description = "Address to push the image to and to pull it from."
  value       = local.ecr_repository_url
}

output "repository_name" {
  description = "Repository name (used in the docker hint output)."
  value       = local.ecr_repository_name
}
