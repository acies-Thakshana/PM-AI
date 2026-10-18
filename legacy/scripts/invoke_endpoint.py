"""Send one question to a deployed SageMaker endpoint."""

from __future__ import annotations

import argparse
import json

import boto3


def main() -> None:
    parser = argparse.ArgumentParser(description="Invoke the AI4BI SageMaker endpoint")
    parser.add_argument("--endpoint-name", default="ai4bi")
    parser.add_argument("--question", required=True)
    parser.add_argument("--domain", default="generic_cube")
    parser.add_argument("--region")
    args = parser.parse_args()

    runtime = boto3.Session(region_name=args.region).client("sagemaker-runtime")
    response = runtime.invoke_endpoint(
        EndpointName=args.endpoint_name,
        ContentType="application/json",
        Body=json.dumps({"question": args.question, "domain": args.domain}).encode("utf-8"),
    )
    print(response["Body"].read().decode("utf-8"))


if __name__ == "__main__":
    main()
