import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import List

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, ValidationError

app = FastAPI(title="Code Interpreter with AI Error Analysis")

# Required by browser-based graders. Restrict origins in a production app.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class CodeRequest(BaseModel):
    code: str = Field(min_length=1, max_length=20_000)


class CodeResponse(BaseModel):
    error: List[int]
    result: str


class ErrorAnalysis(BaseModel):
    error_lines: List[int]


def execute_python_code(code: str) -> dict:
    """Run user code in a separate process and return stdout or the traceback.

    This limits hangs and keeps the API process and AI token out of the child
    process environment. It is not a complete security sandbox; see README.
    """
    with tempfile.TemporaryDirectory(prefix="code-run-") as tmp:
        working_dir = Path(tmp)
        script = working_dir / "user_code.py"
        script.write_text(code, encoding="utf-8")

        # Do not pass server secrets such as AIPIPE_TOKEN to executed code.
        child_env = {
            "PATH": os.environ.get("PATH", ""),
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUNBUFFERED": "1",
        }
        try:
            completed = subprocess.run(
                [sys.executable, "-I", str(script)],
                cwd=working_dir,
                env=child_env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=5,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "output": "TimeoutError: code execution exceeded the 5-second limit.",
            }
        except OSError as exc:
            return {"success": False, "output": f"ExecutionError: {exc}"}

        if completed.returncode == 0:
            return {"success": True, "output": completed.stdout}

        # Python normally writes syntax/runtime tracebacks to stderr.
        error_output = completed.stderr or completed.stdout
        return {"success": False, "output": error_output}


def analyze_error_with_ai(code: str, traceback_text: str) -> List[int]:
    """Use AI Pipe's OpenAI-compatible endpoint to return source line numbers."""
    token = os.environ.get("AIPIPE_TOKEN")
    if not token:
        raise RuntimeError("AIPIPE_TOKEN is not configured on the server.")

    prompt = f"""Identify the 1-based line number(s) in the submitted Python code
that caused the exception. Use the traceback as evidence. Return only a JSON
object with this schema: {{\"error_lines\": [integer, ...]}}. Do not report
line numbers belonging to the API server, temporary runner, or Python library.
If the traceback does not identify a source line, return an empty list.

SUBMITTED CODE:
{code}

TRACEBACK / EXECUTION ERROR:
{traceback_text}
"""

    response = httpx.post(
        "https://aipipe.org/openai/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json={
            "model": "gpt-4.1-nano",
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You analyze Python tracebacks. Respond with valid JSON only, "
                        "matching {\"error_lines\": [integer, ...]}."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0,
        },
        timeout=25.0,
    )
    response.raise_for_status()
    payload = response.json()
    content = payload["choices"][0]["message"]["content"]
    parsed = ErrorAnalysis.model_validate(json.loads(content))

    # Keep only plausible line numbers from the supplied source.
    total_lines = len(code.splitlines())
    return sorted({n for n in parsed.error_lines if 1 <= n <= total_lines})


@app.get("/")
def health_check():
    return {"status": "ok", "endpoint": "/code-interpreter"}


@app.post("/code-interpreter", response_model=CodeResponse)
def code_interpreter(request: CodeRequest):
    execution = execute_python_code(request.code)

    if execution["success"]:
        return CodeResponse(error=[], result=execution["output"])

    try:
        error_lines = analyze_error_with_ai(request.code, execution["output"])
    except (httpx.HTTPError, KeyError, ValueError, ValidationError, RuntimeError, json.JSONDecodeError) as exc:
        # Do not falsely claim analysis succeeded. Preserve the exact execution
        # result so the grader/user can still inspect the real error.
        raise HTTPException(
            status_code=502,
            detail=f"Execution failed, but AI line analysis failed: {type(exc).__name__}: {exc}",
        ) from exc

    return CodeResponse(error=error_lines, result=execution["output"])
