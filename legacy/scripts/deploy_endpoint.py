"""Create a SageMaker real-time endpoint from an image already in Amazon ECR.

Build and push the image first, from this folder:

    docker build -t ai4bi-sagemaker .
    aws ecr get-login-password --region REGION | docker login --username AWS --password-stdin ACCOUNT.dkr.ecr.REGION.amazonaws.com
    docker tag ai4bi-sagemaker:latest ACCOUNT.dkr.ecr.REGION.amazonaws.com/ai4bi-sagemaker:latest
    docker push ACCOUNT.dkr.ecr.REGION.amazonaws.com/ai4bi-sagemaker:latest

Then:

    python scripts/deploy_endpoint.py --image-uri ACCOUNT.dkr.ecr.REGION.amazonaws.com/ai4bi-sagemaker:latest --role-arn arn:aws:iam::ACCOUNT:role/SageMakerRole
"""

from __future__ import annotations

import argparse
import time

import boto3


def main() -> None:
    parser = argparse.ArgumentParser(description="Deploy the AI4BI SageMaker endpoint")
    parser.add_argument("--image-uri", required=True)
    parser.add_argument("--role-arn", required=True)
    parser.add_argument("--endpoint-name", default="ai4bi")
    parser.add_argument("--instance-type", default="ml.m5.large")
    parser.add_argument("--instance-count", type=int, default=1)
    parser.add_argument("--region")
    args = parser.parse_args()

    session = boto3.Session(region_name=args.region)
    client = session.client("sagemaker")
    model_name = f"{args.endpoint_name}-model"
    config_name = f"{args.endpoint_name}-config"

    client.create_model(
        ModelName=model_name,
        ExecutionRoleArn=args.role_arn,
        PrimaryContainer={"Image": args.image_uri, "Mode": "SingleModel", "Environment": {"AIBI_LLM_MODE": "local"}},
    )
    client.create_endpoint_config(
        EndpointConfigName=config_name,
        ProductionVariants=[
            {
                "VariantName": "AllTraffic",
                "ModelName": model_name,
                "InstanceType": args.instance_type,
                "InitialInstanceCount": args.instance_count,
            }
        ],
    )
    client.create_endpoint(EndpointName=args.endpoint_name, EndpointConfigName=config_name)
    print(f"Creating endpoint {args.endpoint_name}")
    while True:
        status = client.describe_endpoint(EndpointName=args.endpoint_name)["EndpointStatus"]
        print(status)
        if status == "InService":
            break
        if status in {"Failed", "RollingBack"}:
            raise SystemExit(f"Endpoint entered {status}")
        time.sleep(30)
    print(f"Endpoint is ready: {args.endpoint_name}")


if __name__ == "__main__":
    main()
