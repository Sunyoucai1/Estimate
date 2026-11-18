"""Call an AI Core model deployment from a local Python process."""
import argparse
import ast
import base64
import json
import math
import os
from pathlib import Path
import time
import urllib.error
import urllib.parse
import urllib.request


def read_settings(env_file):
    settings = {}
    if env_file:
        for line in Path(env_file).read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, separator, value = line.partition("=")
            if separator and key.strip().startswith("AICORE_"):
                value = value.strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                    value = ast.literal_eval(value)
                settings[key.strip()] = value
    settings.update({k: v for k, v in os.environ.items() if k.startswith("AICORE_")})
    return settings


def request_json(url, headers, data=None, timeout=60):
    request = urllib.request.Request(url, headers=headers, data=data)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def connect(settings):
    raw_key = settings.get("AICORE_SERVICE_KEY")
    if not raw_key:
        raise ValueError("Set AICORE_SERVICE_KEY or pass --env-file with existing AI Core credentials.")
    key = json.loads(raw_key)
    auth_url = settings.get("AICORE_AUTH_URL") or key["url"]
    auth_url = auth_url.rstrip("/")
    if not auth_url.endswith("/oauth/token"):
        auth_url += "/oauth/token"
    basic_auth = base64.b64encode(
        (key["clientid"] + ":" + key["clientsecret"]).encode()
    ).decode()
    token = request_json(
        auth_url,
        {"Authorization": "Basic " + basic_auth,
         "Content-Type": "application/x-www-form-urlencoded"},
        data=b"grant_type=client_credentials",
        timeout=30,
    )["access_token"]
    api_url = key["serviceurls"]["AI_API_URL"].rstrip("/")
    headers = {
        "Authorization": "Bearer " + token,
        "AI-Resource-Group": settings.get("AICORE_RESOURCE_GROUP", "assessment-agent-group"),
        "Content-Type": "application/json",
    }
    return api_url, headers


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deployment-id", required=True, help="New model Deployment ID from AI Launchpad")
    parser.add_argument("--env-file", help="Existing .env file containing AICORE_SERVICE_KEY")
    parser.add_argument("--resource-group", help="Override the resource group in the environment file")
    parser.add_argument("--samples", type=Path, default=Path(__file__).resolve().parents[1] / "examples/projects.json")
    args = parser.parse_args()
    try:
        samples = json.loads(args.samples.read_text(encoding="utf-8-sig"))
        if not isinstance(samples, list) or not samples:
            raise ValueError("Samples must be a nonempty JSON array of {name, features} objects.")
        for sample in samples:
            if not isinstance(sample, dict) or not isinstance(sample.get("features"), dict) or not sample["features"]:
                raise ValueError("Every sample needs a nonempty features object.")
            if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in sample["features"].values()):
                raise ValueError("Feature values must be finite numbers.")
        settings = read_settings(args.env_file)
        if args.resource_group:
            settings["AICORE_RESOURCE_GROUP"] = args.resource_group
        api_url, headers = connect(settings)
        deployment_id = urllib.parse.quote(args.deployment_id, safe="")
        deployment = request_json(api_url + "/v2/lm/deployments/" + deployment_id, headers)
        print("Deployment status:", deployment.get("status"))
        if str(deployment.get("status", "")).upper() != "RUNNING":
            raise ValueError("Deployment is not Running yet. Check its status and logs in AI Launchpad.")
        deployment_url = deployment.get("deploymentUrl")
        if not deployment_url:
            raise ValueError("Deployment has no inference URL yet. Wait until it is Running.")
        deployment_url = deployment_url.rstrip("/")
        health = request_json(deployment_url + "/v1/health", headers)
        print("Health:", json.dumps(health))
        if health.get("model_loaded") is not True:
            raise ValueError("The deployed service has not loaded its model. Check deployment logs and the artifact URL.")
        for sample in samples:
            started = time.monotonic()
            response = request_json(
                deployment_url + "/v1/predict", headers,
                data=json.dumps({"features": sample["features"]}, allow_nan=False).encode(),
            )
            predictions = response.get("predictions")
            if not isinstance(predictions, dict) or not predictions:
                raise ValueError("Prediction response is missing a nonempty predictions object.")
            if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0 for v in predictions.values()):
                raise ValueError("Predictions must be finite, nonnegative numbers.")
            print("\nSample:", sample.get("name", "unnamed"))
            print("Latency: %.2f seconds" % (time.monotonic() - started))
            print(json.dumps(predictions, indent=2, ensure_ascii=True))
        print("\nModel loading and inference checks passed. Accuracy requires comparison with actual project effort.")
        return 0
    except urllib.error.HTTPError as exc:
        print("Request failed: HTTP %s. Check credentials/resource group (401/403), deployment/route (404), or deployment logs (5xx)." % exc.code)
    except urllib.error.URLError:
        print("Connection failed. Check network access and AI Core endpoint availability.")
    except (ValueError, KeyError, OSError, SyntaxError) as exc:
        print("Test failed:", type(exc).__name__)
        if isinstance(exc, ValueError) and not isinstance(exc, json.JSONDecodeError):
            print(str(exc))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
