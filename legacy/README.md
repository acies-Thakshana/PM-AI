# AI4BI for SageMaker

This folder is a self-contained copy of the AI4BI project plus a SageMaker real-time inference server. It can be uploaded to SageMaker Studio and tested there. It does not need Dataiku.

The server implements the SageMaker container contract:

- `GET /ping` returns health.
- `POST /invocations` answers a business question.

Local mode uses the bundled sample data and the deterministic SQL planner. No external model call is made.

## Test in SageMaker Studio

1. Upload this folder to a SageMaker Studio notebook or notebook instance.
2. Open `notebooks/test_on_sagemaker.ipynb`.
3. Run all cells.

The notebook calls the same handler the endpoint uses. A successful run returns a status, an answer, the SQL, and the result table for the `generic_cube` sample.

You can also open a terminal in the folder and run:

```bash
pip install -r requirements.txt
python scripts/test_local_endpoint.py
```

## Request

```json
{"question": "What is total Agg Productivity?", "domain": "generic_cube"}
```

`domain` defaults to the domain in `config/settings.yaml`. `persist` defaults to false, so a test call does not rewrite the knowledge graph. Set `"persist": true` to record the question episode.

To refresh learned semantics:

```json
{"action": "onboard", "domain": "generic_cube"}
```

## Deploy a real-time endpoint

From this folder, build the image and push it to Amazon ECR. Then create the endpoint:

```bash
python scripts/deploy_endpoint.py --image-uri ACCOUNT.dkr.ecr.REGION.amazonaws.com/ai4bi-sagemaker:latest --role-arn arn:aws:iam::ACCOUNT:role/SageMakerRole
python scripts/invoke_endpoint.py --endpoint-name ai4bi --question "What is total Agg Productivity?" --domain generic_cube
```

The execution role needs permission to create SageMaker models and endpoints, and to pull the image from ECR.

## What is included

- `lib/python/ai4bi`: question pipeline, semantic layer, and knowledge graph.
- `storage`: sample tables, semantic packages, registry, and knowledge graph.
- `sagemaker_app`: `/ping` and `/invocations` adapter.
- `serve.py` and `Dockerfile`: container entry point on port 8080.
- `notebooks/test_on_sagemaker.ipynb`: Studio test.

The original project notes are in `AI4BI_README.md`.
