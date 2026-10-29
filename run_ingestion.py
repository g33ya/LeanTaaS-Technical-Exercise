import importlib.util
import json
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


BASE_DIR = Path(__file__).resolve().parent
OUTPUT_ROOT = BASE_DIR / "outputs"


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def write_json(path, payload):
    # Replace the destination only after the new content is written.
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)


def main():
    run_id = (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        + "-"
        + uuid.uuid4().hex[:8]
    )

    run_dir = OUTPUT_ROOT / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=False)

    status = {
        "run_id": run_id,
        "status": "running",
        "started_at": utc_now(),
        "finished_at": None,
        "output_directory": str(run_dir),
        "outputs_ready": False,
    }

    def save_status():
        write_json(run_dir / "run_status.json", status)
        write_json(OUTPUT_ROOT / "latest_run.json", status)

    save_status()

    # Retain access to module variables even if execution fails.
    spec = importlib.util.spec_from_file_location(
        "ingestion_run",
        BASE_DIR / "ingestion.py",
    )
    module = importlib.util.module_from_spec(spec)

    try:
        spec.loader.exec_module(module)
        module.main(output_dir=run_dir)

        expected_files = [
            "salesforce_current_clean.csv",
            "salesforce_prior_clean.csv",
            "hubspot_clean.csv",
            "strategic_scorecard_clean.csv",
            "probability_rules_clean.csv",
            "audit_log.csv",
        ]

        missing = [
            filename for filename in expected_files
            if not (run_dir / filename).is_file()
        ]
        if missing:
            raise ValueError(f"Missing output files: {missing}")

    except Exception as error:
        error_trace = traceback.format_exc()
        (run_dir / "error_traceback.txt").write_text(
            error_trace,
            encoding="utf-8",
        )

        # Save original events without guessing their resolution status.
        events = [
            *getattr(module, "all_issues", []),
            *getattr(error, "issues", []),
        ]
        failure_event = {
            "issue_code": "PIPELINE_FAILED",
            "status": "failed",
            "issue": str(error),
            "error_type": type(error).__name__,
        }

        pd.DataFrame([*events, failure_event]).to_csv(
            run_dir / "failure_audit.csv",
            index=False,
            encoding="utf-8-sig",
        )

        status.update({
            "status": "failed",
            "finished_at": utc_now(),
            "error_type": type(error).__name__,
            "error": str(error),
        })
        save_status()

        print(f"\nIngestion failed: {error}")
        print(f"Failure details saved to: {run_dir}")
        raise SystemExit(1)

    status.update({
        "status": "succeeded",
        "finished_at": utc_now(),
        "outputs_ready": True,
    })
    save_status()

    # Updated only after a successful run.
    write_json(OUTPUT_ROOT / "latest_successful_run.json", status)

    print(f"\nIngestion succeeded. Outputs: {run_dir}")


if __name__ == "__main__":
    main()
