#!/usr/bin/python3

from flask import Flask, Response
import subprocess
import os
import yaml
import logging
import gunicorn.app.base
from typing import Dict, List, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Default timeout in seconds
DEFAULT_TIMEOUT = 20

def load_config(config_path: str) -> Dict:
    """
    Load configuration from YAML file.
    """
    try:
        with open(config_path, 'r') as file:
            return yaml.safe_load(file)
    except Exception as e:
        logger.error(f"Failed to load config file: {e}")
        raise

def run_script(script_path: str, args: List[str] = None, timeout: Optional[int] = None) -> str:
    """
    Run a script and return its output.
    
    Args:
        script_path: Path to the script to execute
        args: Optional list of arguments to pass to the script
        timeout: Timeout in seconds (uses DEFAULT_TIMEOUT if not specified)
    """
    if timeout is None:
        timeout = DEFAULT_TIMEOUT
        
    try:
        if not os.path.isfile(script_path):
            raise FileNotFoundError(f"Script not found: {script_path}")
        
        cmd = [script_path]
        if args:
            cmd.extend(args)
            
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        
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

@app.route('/metrics')
def metrics():
    """
    Execute all configured scripts and combine their outputs.
    """
    output = []
    
    # Get default timeout from config, or use DEFAULT_TIMEOUT
    default_timeout = config.get('default_timeout', DEFAULT_TIMEOUT)
    
    for script in config.get('scripts', []):
        script_path = script.get('path')
        script_args = script.get('args', [])
        script_timeout = script.get('timeout', default_timeout)
        
        if not script_path:
            continue
            
        # Resolve relative paths
        if not os.path.isabs(script_path):
            script_path = os.path.join(os.path.dirname(config_file), script_path)
        
        result = run_script(script_path, script_args, timeout=script_timeout)
        output.append(result)
    
    return Response('\n'.join(output), mimetype='text/plain')

class StandaloneApplication(gunicorn.app.base.BaseApplication):
    """
    Gunicorn application for running the Flask app
    """
    def __init__(self, app, options=None):
        self.options = options or {}
        self.application = app
        super().__init__()

    def load_config(self):
        for key, value in self.options.items():
            self.cfg.set(key.lower(), value)

    def load(self):
        return self.application

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Configurable Prometheus exporter')
    parser.add_argument('--config', '-c', default='exporter_config.yml',
                       help='Path to configuration file')
    parser.add_argument('--port', '-p', type=int, default=9092,
                       help='Port to listen on')
    parser.add_argument('--host', default='0.0.0.0',
                       help='Host to bind to')
    parser.add_argument('--workers', '-w', type=int, default=4,
                       help='Number of Gunicorn workers')
    
    args = parser.parse_args()
    
    # Store config file path globally for relative path resolution
    config_file = os.path.abspath(args.config)
    config = load_config(config_file)
    
    logger.info(f"Starting exporter with config from {config_file}")
    
    # Gunicorn options
    options = {
        'bind': f'{args.host}:{args.port}',
        'workers': args.workers,
        'worker_class': 'sync',
        'accesslog': '-',  # Log to stdout
        'errorlog': '-',   # Log to stdout
        'capture_output': True,
        'preload_app': True
    }
    
    StandaloneApplication(app, options).run()
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
    Append instance_id label properly into existing label set (comma-separated).
    If no labels exist, create a new {instance_id="..."} block.
    Comments (#) remain untouched.
    """
    if not instance_id:
        return metrics_output

    new_lines: List[str] = []
    for raw_line in metrics_output.splitlines():
        line = raw_line.rstrip("\n")

        # Skip comments or blank lines
        if not line.strip() or line.lstrip().startswith("#"):
            new_lines.append(line)
            continue

        parts = line.split(None, 1)
        if len(parts) < 2:
            new_lines.append(line)
            continue

        left, right = parts[0], parts[1]

        if "{" in left and "}" in left:
            # Insert instance_id before the last '}'
            pos = left.rfind("}")
            # check if last char before } is { or not to decide comma
            if left[pos - 1] != "{":
                new_left = f'{left[:pos]},{f"instance_id=\"{instance_id}\""}{left[pos:]}'
            else:
                new_left = f'{left[:pos]}instance_id="{instance_id}"{left[pos:]}'
        else:
            # No labels exist — create a new one
            new_left = f'{left}{{instance_id="{instance_id}"}}'

        new_lines.append(f"{new_left} {right}")

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