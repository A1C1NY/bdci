"""Execute trusted local Python experiments. This is NOT a code sandbox."""

import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from .storage import read_json, utc_now, write_json


def validate_result(path, method, seed, metric):
    value = read_json(path)
    if (not isinstance(value, dict) or value.get("method") != method
            or type(value.get("seed")) is not int or value.get("seed") != seed):
        raise ValueError("Result identity does not match requested method/seed")
    metrics = value.get("metrics")
    if not isinstance(metrics, dict) or metric not in metrics:
        raise ValueError("Result missing primary metric")
    for name, number in metrics.items():
        if type(number) not in (float, int) or not math.isfinite(number):
            raise ValueError(f"Non-finite or nonnumeric metric: {name}")
    if not isinstance(value.get("provenance"), dict):
        raise ValueError("Result must include provenance")
    return value


def terminate_tree(process):
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if process.poll() is None:
        process.kill()
    process.wait()


def execute(script, method, seed, directory, timeout, metric):
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    result_path = directory / "result.json"
    command = [sys.executable, str(script), "--method", method, "--seed", str(seed),
               "--output", str(result_path)]
    record = {"method": method, "seed": seed, "started_at": utc_now(),
              "command": command, "status": "running"}
    write_json(directory / "execution.json", record)
    start = time.perf_counter()
    try:
        with (directory / "stdout.log").open("wb") as out, (directory / "stderr.log").open("wb") as err:
            options = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"
            process = subprocess.Popen(command, cwd=directory, stdout=out, stderr=err,
                                       env=env, shell=False, **options)
            try:
                record["returncode"] = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                terminate_tree(process)
                raise TimeoutError(f"Experiment exceeded {timeout} seconds")
            except BaseException:
                terminate_tree(process)
                raise
        if record["returncode"] != 0:
            raise RuntimeError(f"Experiment exited with code {record['returncode']}; see stderr.log")
        validate_result(result_path, method, seed, metric)
        record["status"] = "completed"
    except Exception as exc:
        record["status"] = "failed"
        record["error"] = str(exc)
    except BaseException as exc:
        record["status"] = "interrupted"
        record["error"] = type(exc).__name__
        raise
    finally:
        record["wall_seconds"] = time.perf_counter() - start
        record["finished_at"] = utc_now()
        write_json(directory / "execution.json", record)
    return record
