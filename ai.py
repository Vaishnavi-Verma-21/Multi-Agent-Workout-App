# ai.py
from langflow.load import run_flow_from_json
from dotenv import load_dotenv
import requests
from typing import Optional, Dict, Any
import json
import os
import re

load_dotenv()

BASE_API_URL = "https://api.langflow.astra.datastax.com"
LANGFLOW_ID = "34c16f5c-70e4-4bb6-9c51-89a41a653efd"
APPLICATION_TOKEN = os.getenv("LANGFLOW_TOKEN")  # make sure this is set in your env


def dict_to_string(obj, level=0):
    strings = []
    indent = "  " * level
    if isinstance(obj, dict):
        for key, value in obj.items():
            if isinstance(value, (dict, list)):
                nested_string = dict_to_string(value, level + 1)
                strings.append(f"{indent}{key}: {nested_string}")
            else:
                strings.append(f"{indent}{key}: {value}")
    elif isinstance(obj, list):
        for idx, item in enumerate(obj):
            nested_string = dict_to_string(item, level + 1)
            strings.append(f"{indent}Item {idx + 1}: {nested_string}")
    else:
        strings.append(f"{indent}{obj}")
    return ", ".join(strings)


def _find_text_in_obj(obj) -> Optional[str]:
    if obj is None:
        return None
    if isinstance(obj, str):
        return obj if obj.strip() else None
    if isinstance(obj, dict):
        # common deep path used by Langflow responses
        for key in ("outputs", "results", "text", "data", "message", "result"):
            if key in obj:
                found = _find_text_in_obj(obj[key])
                if found:
                    return found
        # otherwise search all values
        for v in obj.values():
            found = _find_text_in_obj(v)
            if found:
                return found
    if isinstance(obj, list):
        for item in obj:
            found = _find_text_in_obj(item)
            if found:
                return found
    return None


def run_flow(
    message: str,
    output_type: str = "chat",
    input_type: str = "chat",
    tweaks: Optional[dict] = None,
    application_token: Optional[str] = None,
) -> Dict[str, Any]:
    api_url = f"{BASE_API_URL}/lf/{LANGFLOW_ID}/api/v1/run/macros"
    payload = {
        "input_value": message,
        "output_type": output_type,
        "input_type": input_type,
    }
    if tweaks:
        payload["tweaks"] = tweaks

    headers = {"Content-Type": "application/json"}
    if application_token:
        headers["Authorization"] = f"Bearer {application_token}"

    try:
        resp = requests.post(api_url, json=payload, headers=headers, timeout=30)
    except Exception as e:
        return {"error": f"request_failed: {e}", "raw_text": None, "raw_json": None}

    # Try to parse JSON
    raw_json = None
    try:
        raw_json = resp.json()
    except Exception:
        raw_json = None

    raw_text = None
    if raw_json is not None:
        raw_text = _find_text_in_obj(raw_json)

    if raw_text is None:
        # fallback to plain response text
        raw_text = resp.text if resp.text and resp.text.strip() else None

    return {"raw_text": raw_text, "raw_json": raw_json, "status_code": resp.status_code}


def ask_ai(profile: dict, question: str) -> Dict[str, Any]:
    TWEAKS = {
        "TextInput-XjIKI": {"input_value": question},
        "TextInput-176Ns": {"input_value": dict_to_string(profile)},
    }

    # Prefer run_flow_from_json (local Langflow loader) if it exists and works
    try:
        result = run_flow_from_json(
            flow="AskAIV2.json",
            input_value="message",
            fallback_to_env_vars=True,
            tweaks=TWEAKS,
        )
        # try to extract text in a few ways
        try:
            text = result[0].outputs[0].results["text"].data["text"]
            return {"text": text, "raw": result}
        except Exception:
            # fallback to converting to string
            return {"text": str(result), "raw": result}
    except Exception:
        # fallback to API run
        res = run_flow(question, tweaks=TWEAKS, application_token=APPLICATION_TOKEN)
        return {"text": res.get("raw_text") or "", "raw": res}


def _parse_number(s: str) -> Optional[int]:
    """Turn a numeric-like string into int (remove commas); return None if not possible."""
    if not s:
        return None
    s = s.replace(",", "")
    m = re.search(r"-?\d+(\.\d+)?", s)
    if not m:
        return None
    try:
        # prefer integer
        val = float(m.group(0))
        return int(round(val))
    except Exception:
        return None


def parse_macros_from_text(text: str, fallback: Optional[dict] = None) -> dict:
    fallback = fallback or {}
    parsed = {"calories": None, "protein": None, "fat": None, "carbs": None}
    debug = []

    if not text:
        debug.append("no text to parse")
    else:
        lower = text.lower()
        # patterns to try for each macro
        patterns = {
            "calories": [r"calories?\s*[:\-]?\s*([0-9,\.]+)", r"calories?\s*[:\-]?\s*([0-9,\.]+)\s*kcal"],
            "protein": [r"protein\s*[:\-]?\s*([0-9,\.]+)", r"protein\s*[:\-]?\s*([0-9,\.]+)\s*g"],
            "fat": [r"fat\s*[:\-]?\s*([0-9,\.]+)", r"fat\s*[:\-]?\s*([0-9,\.]+)\s*g"],
            "carbs": [r"(carbs|carbohydrates)\s*[:\-]?\s*([0-9,\.]+)", r"(carbs|carbohydrates)\s*[:\-]?\s*([0-9,\.]+)\s*g"],
        }
        for key, pats in patterns.items():
            for p in pats:
                m = re.search(p, text, flags=re.IGNORECASE)
                if m:
                    # groups differ for carbs pattern (two groups), pick last numeric group
                    num_group = m.groups()[-1]
                    val = _parse_number(num_group)
                    if val is not None:
                        parsed[key] = val
                        debug.append(f"matched {key} with pattern {p}: {val}")
                        break

        # If none matched, try to extract all numbers and heuristically assign
        if all(v is None for v in parsed.values()):
            nums = re.findall(r"\d{2,5}(?:,\d{3})?(?:\.\d+)?", text)  # numbers of plausible macro sizes
            nums_int = [int(n.replace(",", "").split(".")[0]) for n in nums[:10]]
            debug.append(f"heuristic numbers found: {nums_int}")
            if nums_int:
                # heuristics: largest number -> calories (if > 500), others map to protein/fat/carbs
                nums_sorted = sorted(nums_int, reverse=True)
                if nums_sorted[0] > 500:
                    parsed["calories"] = nums_sorted[0]
                    debug.append(f"assigned calories={nums_sorted[0]} by heuristic")
                    # assign remaining in order to protein/fat/carbs if present
                    rest = nums_sorted[1:]
                    if rest:
                        parsed["protein"] = rest[0] if len(rest) > 0 else None
                        parsed["fat"] = rest[1] if len(rest) > 1 else None
                        parsed["carbs"] = rest[2] if len(rest) > 2 else None
                else:
                    # if all small numbers, try map to protein/fat/carbs
                    if len(nums_sorted) >= 3:
                        parsed["protein"], parsed["fat"], parsed["carbs"] = nums_sorted[:3]
                        debug.append("assigned protein/fat/carbs from first three numbers")
    # Fill from fallback (profile nutrition) if available and still None
    for k in ("calories", "protein", "fat", "carbs"):
        if parsed[k] is None and fallback and k in fallback:
            parsed[k] = int(fallback.get(k, 0) or 0)
            debug.append(f"filled {k} from fallback profile")

    # final safe default (0) — but we prefer not to silently return zeros; keep them as ints
    for k in parsed:
        parsed[k] = int(parsed[k] or 0)

    return {"calories": parsed["calories"], "protein": parsed["protein"], "fat": parsed["fat"], "carbs": parsed["carbs"], "raw_text": text, "parse_debug": debug}


def get_macros(profile: dict, goals: list) -> dict:
    # Make sure profile and goals are in expected formats
    profile_text = dict_to_string(profile or {})
    goals_list = goals or []
    if isinstance(goals_list, str):
        goals_list = [goals_list]

    TWEAKS = {
        # THESE NODE IDs MUST MATCH your Langflow flow's text input node ids.
        # If your flow uses different node IDs, update them here.
        "TextInput-PR5Jb": {"input_value": ", ".join(goals_list)},
        "TextInput-PrfY9": {"input_value": profile_text},
    }

    # call API
    res = run_flow("", tweaks=TWEAKS, application_token=APPLICATION_TOKEN)

    text = res.get("raw_text") if isinstance(res, dict) else None
    parsed = parse_macros_from_text(text, fallback=profile.get("nutrition") if profile else None)

    # include raw_json and status_code to help debugging in UI
    parsed["raw_json"] = res.get("raw_json") if isinstance(res, dict) else None
    parsed["status_code"] = res.get("status_code") if isinstance(res, dict) else None

    return parsed
