#!/usr/bin/python3

from flask import Flask, Response
import subprocess
import os
import yaml
import logging
import gunicorn.app.base
from typing import Dict, List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Default timeout and limits
DEFAULT_TIMEOUT = 20
MAX_WORKERS_CAP = 10  # Safety cap

def load_config(config_path: str) -> Dict:
    """
    Load configuration from YAML file.
    """
    try:
        with open(config_path, 'r') as file:
            return yaml.safe_load(file) or {}
    except Exception as e:
        logger.error(f"Failed to load config file: {e}")
        raise

def run_script(script_path: str, args: List[str] = None, timeout: Optional[int] = None) -> str:
    """
    Run a script and return its output.
    """
    if timeout is None:
        timeout = DEFAULT_TIMEOUT
    try:
        if not os.path.isfile(script_path):
            raise FileNotFoundError(f"Script not found: {script_path}")

        cmd = [script_path]
        if args:
            cmd.extend(args)

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)

        if result.returncode != 0:
            logger.error(f"Script {script_path} failed with error: {result.stderr}")
            return f"# ERROR: Script {os.path.basename(script_path)} failed\n"

        return result.stdout
    except subprocess.TimeoutExpired:
        logger.error(f"Script {script_path} timed out after {timeout} seconds")
        return f"# ERROR: Script {os.path.basename(script_path)} timed out after {timeout}s\n"
    except Exception as e:
        logger.error(f"Error running script {script_path}: {e}")
        return f"# ERROR: Failed to run script {os.path.basename(script_path)}: {str(e)}\n"

def add_instance_label(metrics_output: str, instance_id: Optional[str]) -> str:
    """
    Safely merge instance_id="..." into the metric's label set.
    - Leaves comments (#) and blank lines untouched.
    - If no labels exist, creates {instance_id="..."}.
    - If labels exist, appends ,instance_id="..." before the closing }.
    - Does not inject inside quoted strings.
    - Skips if instance_id already present.
    """
    if not instance_id:
        return metrics_output

    def has_instance_id(label_block: str) -> bool:
        # crude but safe enough: look for instance_id= outside quotes
        in_q = False
        i = 0
        while i < len(label_block):
            c = label_block[i]
            if c == '"':
                in_q = not in_q
            if not in_q and label_block.startswith('instance_id=', i):
                return True
            i += 1
        return False

    def find_labelset_bounds(token: str) -> Optional[tuple]:
        """
        token == '<metricname>' or '<metricname>{...}'
        Return (open_idx, close_idx) of the top-level { ... } if present, else None.
        Correctly skips braces inside quotes.
        Must find the FIRST '{' that is NOT inside a quoted string.
        """
        if "{" not in token:
            return None

        # Find the first '{' that's not inside quotes
        in_q = False
        open_idx = -1
        for i in range(len(token)):
            ch = token[i]
            if ch == '"':
                in_q = not in_q
            elif not in_q and ch == "{":
                open_idx = i
                break

        if open_idx == -1:
            return None  # no '{' found outside quotes

        # Now find matching '}' from open_idx onwards
        in_q = False
        depth = 0
        for i in range(open_idx, len(token)):
            ch = token[i]
            if ch == '"':
                in_q = not in_q
            elif not in_q:
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        return (open_idx, i)
        return None  # malformed; let caller treat as no-labels

    new_lines = []
    for raw in metrics_output.splitlines():
        line = raw.rstrip("\n")

        # pass through comments / blanks
        if not line.strip() or line.lstrip().startswith("#"):
            new_lines.append(line)
            continue

        # Find where the metric name + labels ends (before the value)
        # We need to find the end of the label set (if it exists) or metric name
        # then take everything after that as the value

        in_quotes = False
        metric_end = -1

        for i, ch in enumerate(line):
            if ch == '"':
                in_quotes = not in_quotes
            elif not in_quotes:
                if ch == '{':
                    # Found label set, need to find its end
                    depth = 1
                    j = i + 1
                    while j < len(line) and depth > 0:
                        if line[j] == '"':
                            in_quotes = not in_quotes
                        elif not in_quotes:
                            if line[j] == '{':
                                depth += 1
                            elif line[j] == '}':
                                depth -= 1
                        j += 1
                    metric_end = j
                    break
                elif ch == ' ' or ch == '\t':
                    # No labels, metric name ends here
                    metric_end = i
                    break

        if metric_end == -1:
            # No space found, entire line is metric name (no value)
            new_lines.append(line)
            continue

        left = line[:metric_end]
        right = line[metric_end:]

        # Check if this metric has labels
        bounds = find_labelset_bounds(left)
        if bounds is None:
            # no labels: create one
            new_left = f'{left}{{instance_id="{instance_id}"}}'
            new_lines.append(f"{new_left}{right}")
            continue

        open_i, close_i = bounds
        before_label = left[:open_i+1]          # includes '{'
        labels = left[open_i+1:close_i]   # inside braces
        after_label = left[close_i:]            # includes '}'

        # If already present, do nothing
        if has_instance_id(labels):
            new_lines.append(line)
            continue

        # Determine if we need a comma (non-empty labels without trailing comma)
        trimmed = labels.strip()
        if trimmed == "":
            merged = f'instance_id="{instance_id}"'
        else:
            # ensure there's a comma between existing labels and the new one
            merged = labels.rstrip()
            if not merged.endswith(","):
                merged += ","
            merged += f'instance_id="{instance_id}"'

        new_left = f"{before_label}{merged}{after_label}"
        new_lines.append(f"{new_left}{right}")

    return "\n".join(new_lines)

@app.route('/metrics')
def metrics():
    """
    Execute all configured scripts and combine outputs.
    Supports parallel execution via max_workers (capped).
    """
    output_chunks: List[Tuple[int, str]] = []

    default_timeout = config.get('default_timeout', DEFAULT_TIMEOUT)
    instance_id = config.get('instance_id', None)
    scripts = config.get('scripts', []) or []

    configured_workers = config.get('max_workers', None)
    if configured_workers is None:
        max_workers = min(len(scripts) if scripts else 1, MAX_WORKERS_CAP)
    else:
        try:
            max_workers = max(1, min(int(configured_workers), MAX_WORKERS_CAP))
        except Exception:
            max_workers = 1


    tasks: List[Tuple[int, str, List[str], int]] = []
    for idx, script in enumerate(scripts):
        if not isinstance(script, dict):
            continue
        script_path = script.get('path')
        if not script_path:
            continue
        if not os.path.isabs(script_path):
            script_path = os.path.join(os.path.dirname(config_file), script_path)
        args = script.get('args', [])
        timeout = script.get('timeout', default_timeout)
        tasks.append((idx, script_path, args, timeout))

    if not tasks:
        return Response("# No scripts configured\n", mimetype='text/plain')

    # Parallel execution
    if max_workers > 1:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(run_script, sp, sa, t): idx
                for (idx, sp, sa, t) in tasks
            }
            for f in as_completed(futures):
                idx = futures[f]
                try:
                    result = f.result()
                except Exception as e:
                    logger.exception(f"Exception running script index {idx}: {e}")
                    result = f"# ERROR: Exception running script {idx}\n"
                result = add_instance_label(result, instance_id)
                output_chunks.append((idx, result))
    else:
        for idx, sp, sa, t in tasks:
            result = run_script(sp, sa, timeout=t)
            result = add_instance_label(result, instance_id)
            output_chunks.append((idx, result))

    output_chunks.sort(key=lambda x: x[0])
    combined = "\n".join(chunk for _, chunk in output_chunks)
    return Response(combined, mimetype='text/plain')

class StandaloneApplication(gunicorn.app.base.BaseApplication):
    def __init__(self, app, options=None):
        self.options = options or {}
        self.application = app
        super().__init__()

    def load_config(self):
        for k, v in self.options.items():
            self.cfg.set(k.lower(), v)

    def load(self):
        return self.application

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Configurable Prometheus exporter')
    parser.add_argument('--config', '-c', default='exporter_config.yml', help='Path to configuration file')
    parser.add_argument('--port', '-p', type=int, help='Port to listen on (overrides config)')
    parser.add_argument('--host', default='0.0.0.0', help='Host to bind')
    parser.add_argument('--workers', '-w', type=int, default=4, help='Gunicorn worker count')

    args = parser.parse_args()

    config_file = os.path.abspath(args.config)
    config = load_config(config_file)

    # Port precedence: CLI > config > default (9092)
    port = args.port or config.get('port', 9092)

    logger.info(f"Starting exporter with config from {config_file} on port {port}")

    options = {
        'bind': f'{args.host}:{port}',
        'workers': args.workers,
        'worker_class': 'sync',
        'accesslog': '-',
        'errorlog': '-',
        'capture_output': True,
        'preload_app': True
    }

    StandaloneApplication(app, options).run()
