#!/usr/bin/python3

from flask import Flask, Response
import subprocess
import os
import yaml
import logging
import gunicorn.app.base
from typing import Dict, List

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

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

def run_script(script_path: str, args: List[str] = None) -> str:
    """
    Run a script and return its output.
    """
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
            timeout=30  # Add timeout to prevent hanging
        )
        
        if result.returncode != 0:
            logger.error(f"Script {script_path} failed with error: {result.stderr}")
            return f"# ERROR: Script {os.path.basename(script_path)} failed\n"
            
        return result.stdout
    except Exception as e:
        logger.error(f"Error running script {script_path}: {e}")
        return f"# ERROR: Failed to run script {os.path.basename(script_path)}: {str(e)}\n"

@app.route('/metrics')
def metrics():
    """
    Execute all configured scripts and combine their outputs.
    """
    output = []
    
    for script in config.get('scripts', []):
        script_path = script.get('path')
        script_args = script.get('args', [])
        
        if not script_path:
            continue
            
        # Resolve relative paths
        if not os.path.isabs(script_path):
            script_path = os.path.join(os.path.dirname(config_file), script_path)
        
        result = run_script(script_path, script_args)
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
