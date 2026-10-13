# Experience layer (frozen)

Hybrid shell for every AI4BI project:

1. Dashboard — orientation
2. Copilot — exploration
3. Drill-down — investigation
4. Visuals — consumption

Power-user shadowing informs UX priority. It does not block or fork this design.

## Stable vs configurable

See `config/platform.yaml`.

| Stable | Configurable |
|--------|----------------|
| Visualization engine (`config/visual_templates.yaml`) | `onboarding/domains/<d>/visuals.yaml` |
| Drill engine (`aibi/experience/drill.py`) | entities, dimensions, filters, actions |
| Explainability engine | `explainability.yaml` level flags |
| Excel Escape runner | `evaluation/excel_escape/<d>.yaml` |
| Frontend shell | card list, default prompts |

## Commands

```powershell
cd C:\Users\BharadNa\enterprise-ai-for-bi
py -3 run_onboard.py experience --domain service_ops
py -3 run_onboard.py eval --domain service_ops
py -3 -m pytest tests/experience -q
```
