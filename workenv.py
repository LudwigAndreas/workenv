#!/usr/bin/env python3.11
"""
WorkEnv - A tool to automate daily project tasks with configurable actions

WorkEnv allows you to define projects and associated actions in a YAML configuration
file, then run those actions with a simple command line interface.
"""

import os
import sys
import yaml
import shlex
import argparse
import subprocess
import logging
import tempfile
from pathlib import Path
from string import Template


# Configuration constants
APP_NAME = "workenv"
DEFAULT_CONFIG_DIRS = [
    os.path.join(os.path.expanduser("~"), f".config/{APP_NAME}"),
    os.path.join(os.path.expanduser("~"), f".{APP_NAME}"),
    os.path.join("/etc", APP_NAME),
]
DEFAULT_CONFIG_FILE = "config.yaml"
ENV_CONFIG_PATH = "WORKENV_CONFIG_PATH"


def setup_logging(verbose=False):
    """Configure logging based on verbosity level."""
    log_level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(levelname)s: %(message)s"
    )
    return logging.getLogger(APP_NAME)


def get_config_path():
    """
    Determine the path to the configuration file.
    Order of precedence:
    1. Environment variable WORKENV_CONFIG_PATH
    2. ~/.config/workenv/config.yaml
    3. ~/.workenv/config.yaml
    4. /etc/workenv/config.yaml
    """
    # Check environment variable
    if ENV_CONFIG_PATH in os.environ:
        config_path = os.path.expanduser(os.environ[ENV_CONFIG_PATH])
        if os.path.isdir(config_path):
            config_path = os.path.join(config_path, DEFAULT_CONFIG_FILE)
        return config_path

    # Check standard config locations
    for config_dir in DEFAULT_CONFIG_DIRS:
        config_path = os.path.join(config_dir, DEFAULT_CONFIG_FILE)
        if os.path.isfile(config_path):
            return config_path

    # If we reach here, no config file was found
    return None


def ensure_config_dir():
    """
    Ensure that the configuration directory exists.
    Returns the path to the configuration directory.
    """
    # Use the first default location
    config_dir = DEFAULT_CONFIG_DIRS[0]
    
    # Create directory if it doesn't exist
    if not os.path.exists(config_dir):
        try:
            os.makedirs(config_dir, exist_ok=True)
            print(f"Created configuration directory: {config_dir}")
        except Exception as e:
            print(f"Error creating configuration directory: {e}")
            sys.exit(1)
    
    return config_dir


def create_default_config(config_path):
    """Create a default configuration file."""
    default_config = {
        "env": {
            "PATH": "$PATH:$WORKENV_CONFIG/bin",
            "WORKENV_ACTIVE": "true"
        },
        "shell": {
            "init": [
                "source $WORKENV_CONFIG/shell/init.sh"
            ]
        },
        "projects": {
            "example": {
                "path": "~/Projects/example",
                "env": {
                    "PROJECT_ROOT": "$project.path"
                },
                "actions": [
                    {"name": "cd"},
                    {"name": "git_fetch"},
                    {"name": "open", "args": "code"}
                ]
            }
        },
        "actions": {
            "cd": [
                {"exec": "cd $project_path"}
            ],
            "git_fetch": [
                {"exec": "git fetch --all"}
            ],
            "open": [
                {"exec": "$EDITOR ${args[@]}"}
            ]
        }
    }
    
    try:
        with open(config_path, 'w') as file:
            yaml.dump(default_config, file, default_flow_style=False)
        
        # Create shell directory and init.sh
        shell_dir = os.path.join(os.path.dirname(config_path), "shell")
        os.makedirs(shell_dir, exist_ok=True)
        
        # Create a sample init.sh file
        init_sh_path = os.path.join(shell_dir, "init.sh")
        with open(init_sh_path, 'w') as file:
            file.write("""#!/bin/bash
# This file is sourced by workenv before running any action
# You can define functions and variables here that will be available to all actions

function git_sync() {
    git fetch --all
    git pull --rebase
}

# Add your custom functions and variables below
""")
        os.chmod(init_sh_path, 0o755)
        
        # Create bin directory
        bin_dir = os.path.join(os.path.dirname(config_path), "bin")
        os.makedirs(bin_dir, exist_ok=True)
        
        print(f"Created default configuration file: {config_path}")
        print("Please edit this file to define your projects and actions.")
    except Exception as e:
        print(f"Error creating default configuration: {e}")
        sys.exit(1)


def load_config(logger, config_path=None):
    """Load and parse the YAML configuration file."""
    # Determine config path if not provided
    if not config_path:
        config_path = get_config_path()
    
    # If no config file exists, create default one
    if not config_path or not os.path.isfile(config_path):
        logger.warning("No configuration file found.")
        config_dir = ensure_config_dir()
        config_path = os.path.join(config_dir, DEFAULT_CONFIG_FILE)
        create_default_config(config_path)
        sys.exit(0)
    
    try:
        with open(config_path, 'r') as file:
            config = yaml.safe_load(file)
            logger.debug(f"Loaded configuration from {config_path}")
            return config, config_path
    except yaml.YAMLError as e:
        logger.error(f"Error parsing YAML configuration: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Error loading configuration: {e}")
        sys.exit(1)


def build_context(config, project_name, command_args, config_path, specific_action=None):
    """Build the context dictionary with all variables needed for substitution."""
    if project_name not in config.get('projects', {}):
        raise ValueError(f"Project '{project_name}' not defined in configuration.")
    
    project_config = config['projects'][project_name]
    
    # Process command arguments
    args_list = []
    if command_args:
        args_list = command_args
    args_str = ' '.join(args_list) if args_list else ''
    
    # Create basic context with all available information
    context = {
        'project_name': project_name,
        'project_path': os.path.expanduser(project_config.get('path', '')),
        'args': args_str,
        'workenv_path': os.getcwd(),
        'config_path': os.path.dirname(os.path.abspath(os.path.expanduser(config_path)))
    }
    
    # Add environment variables to the context
    for key, value in os.environ.items():
        context[key] = value
    
    # Add special context values to maintain backward compatibility
    context['project.name'] = context['project_name']
    context['project.path'] = context['project_path']
    context['project.args'] = context['args']
    context['workenv.args'] = context['args']
    context['workenv.path'] = context['workenv_path']
    context['WORKENV_CONFIG'] = context['config_path']
    
    # Add project actions information to context
    if 'actions' in project_config:
        for idx, action_item in enumerate(project_config['actions']):
            if isinstance(action_item, dict):  # Handle extended syntax
                action_name = action_item.get('name', '')
                action_args = action_item.get('args', '')
                context[f'project.actions.{action_name}.name'] = action_name
                context[f'project.actions.{action_name}.args'] = action_args
            elif isinstance(action_item, str):  # Handle simple syntax
                context[f'project.actions.{action_item}.name'] = action_item
    
    return context


def prepare_env_for_execution(config, project_config, context, logger):
    """Prepare environment variables for command execution."""
    env = os.environ.copy()
    
    # Add global environment variables from config
    if 'env' in config:
        for key, value in config['env'].items():
            # Substitute variables in the value
            value = os.path.expandvars(str(value))
            for var_name, var_value in context.items():
                value = value.replace(f"${var_name}", str(var_value))
                value = value.replace(f"${{var_name}}", str(var_value))
            env[key] = value
    
    # Add project-specific environment variables
    if 'env' in project_config:
        for key, value in project_config['env'].items():
            # Substitute variables in the value
            value = os.path.expandvars(str(value))
            for var_name, var_value in context.items():
                value = value.replace(f"${var_name}", str(var_value))
                value = value.replace(f"${{var_name}}", str(var_value))
            env[key] = value
    
    # Set workenv-specific variables
    env['WORKENV_PROJECT'] = context['project_name']
    env['WORKENV_PROJECT_PATH'] = context['project_path']
    env['WORKENV_CONFIG_PATH'] = context['config_path']
    
    return env


def prepare_shell_script(command, context, config, project_config, temp_dir, logger):
    """Create a temporary shell script that includes environment setup and command execution."""
    script_path = os.path.join(temp_dir, "workenv_command.sh")
    
    with open(script_path, 'w') as script:
        script.write("#!/bin/bash\n")
        script.write("set -e\n\n")
        
        # Add environment variables
        for key, value in context.items():
            if isinstance(value, str):
                # Sanitize the variable name by replacing dots with underscores
                sanitized_key = key.replace('.', '_')
                script.write(f"export {sanitized_key}=\"{value}\"\n")
        
        # Add global shell initialization
        if 'shell' in config and 'init' in config['shell']:
            for init_line in config['shell']['init']:
                expanded_line = os.path.expandvars(init_line)
                for var_name, var_value in context.items():
                    if isinstance(var_value, str):
                        expanded_line = expanded_line.replace(f"${var_name}", var_value)
                        expanded_line = expanded_line.replace(f"${{var_name}}", var_value)
                script.write(f"{expanded_line}\n")
        
        # Add project-specific shell initialization
        if 'shell' in project_config and 'init' in project_config['shell']:
            for init_line in project_config['shell']['init']:
                expanded_line = os.path.expandvars(init_line)
                for var_name, var_value in context.items():
                    if isinstance(var_value, str):
                        expanded_line = expanded_line.replace(f"${var_name}", var_value)
                        expanded_line = expanded_line.replace(f"${{var_name}}", var_value)
                script.write(f"{expanded_line}\n")
        
        # Define args array
        if context['args']:
            args = shlex.split(context['args'])
            script.write("args=(\n")
            for arg in args:
                script.write(f"  \"{arg}\"\n")
            script.write(")\n\n")
        else:
            script.write("args=()\n\n")
        
        # Add the actual command to execute
        script.write(f"{command}\n")
    
    # Make the script executable
    os.chmod(script_path, 0o755)
    logger.debug(f"Created temporary script: {script_path}")
    return script_path


def execute_action(action_name, config, context, temp_dir, logger):
    """Execute a specific action from the configuration."""
    # Check if action exists
    if action_name not in config.get('actions', {}):
        logger.error(f"Action '{action_name}' not defined in configuration.")
        return False
    
    action_config = config['actions'][action_name]
    logger.debug(f"Executing action: {action_name}")
    
    # Get project config
    project_name = context['project_name']
    project_config = config['projects'][project_name]
    
    # Prepare environment for execution
    env = prepare_env_for_execution(config, project_config, context, logger)
    
    for step in action_config:
        # Get the command to execute
        command = step.get('exec', '')
        if not command:
            logger.warning(f"Empty command in action '{action_name}', skipping")
            continue
        
        # Create a temporary shell script for execution
        script_path = prepare_shell_script(command, context, config, project_config, temp_dir, logger)
        
        # Execute the command
        try:
            logger.info(f"Executing action '{action_name}': {command}")
            
            # Special handling for 'cd' command since it affects the process state
            if command.strip().startswith('cd '):
                target_dir = command.strip()[3:].strip()
                target_dir = os.path.expanduser(target_dir)
                # Replace variables in the target_dir
                for var_name, var_value in context.items():
                    if isinstance(var_value, str):
                        target_dir = target_dir.replace(f"${var_name}", var_value)
                        target_dir = target_dir.replace(f"${{var_name}}", var_value)
                
                os.chdir(target_dir)
                logger.info(f"Changed directory to: {target_dir}")
            else:
                # For other commands, use the shell script
                result = subprocess.run(["/bin/bash", script_path], env=env, check=True)
                if result.returncode != 0:
                    logger.error(f"Command '{command}' failed with exit code {result.returncode}")
                    return False
        except subprocess.CalledProcessError as e:
            logger.error(f"Error executing command: {e}")
            return False
        except Exception as e:
            logger.error(f"Error: {e}")
            return False
    
    return True


def run_project(project_name, config, context, logger, specific_action=None):
    """Run all actions for a project, or a specific action if provided."""
    if project_name not in config.get('projects', {}):
        logger.error(f"Project '{project_name}' not defined in configuration.")
        return False
    
    project_config = config['projects'][project_name]
    logger.debug(f"Running project: {project_name}")
    
    # Create a temporary directory for shell scripts
    with tempfile.TemporaryDirectory() as temp_dir:
        # Get project directory
        project_path = project_config.get('path', '')
        original_dir = os.getcwd()
        
        if project_path:
            try:
                project_path = os.path.expanduser(project_path)
                os.chdir(project_path)
                logger.info(f"Changed to project directory: {project_path}")
            except Exception as e:
                logger.error(f"Error changing to project directory: {e}")
                return False
        
        success = True
        
        try:
            if specific_action:
                # Run only the specific action
                success = execute_action(specific_action, config, context, temp_dir, logger)
            else:
                # Run all actions in the project
                if 'actions' in project_config:
                    for action_item in project_config['actions']:
                        if isinstance(action_item, dict):  # Handle extended syntax
                            action_name = action_item.get('name', '')
                        else:  # Handle simple syntax
                            action_name = action_item
                        
                        if not execute_action(action_name, config, context, temp_dir, logger):
                            success = False
                            break
        finally:
            # Change back to original directory if we changed it
            if project_path:
                os.chdir(original_dir)
                logger.debug(f"Changed back to original directory: {original_dir}")
        
        return success


def list_projects(config):
    """List all available projects."""
    print("\nAvailable projects:")
    print("-" * 50)
    for project_name, project_data in config.get('projects', {}).items():
        path = project_data.get('path', 'No path specified')
        print(f"{project_name:20} - {path}")
        
        # List actions for this project
        if 'actions' in project_data:
            print(f"  Actions:")
            for action in project_data['actions']:
                if isinstance(action, dict):
                    action_name = action.get('name', '')
                    args = action.get('args', '')
                    print(f"    - {action_name}" + (f" (args: {args})" if args else ""))
                else:
                    print(f"    - {action}")
        
        # List environment variables for this project
        if 'env' in project_data:
            print(f"  Environment:")
            for key, value in project_data['env'].items():
                print(f"    - {key}={value}")
    print("-" * 50)


def list_actions(config):
    """List all available actions."""
    print("\nAvailable actions:")
    print("-" * 50)
    for action_name, action_steps in config.get('actions', {}).items():
        print(f"{action_name}")
        for step in action_steps:
            exec_cmd = step.get('exec', 'No command')
            print(f"  - {exec_cmd}")
    print("-" * 50)


def show_config_path():
    """Show the current configuration path."""
    config_path = get_config_path()
    if config_path:
        print(f"Current configuration file: {config_path}")
    else:
        print(f"No configuration file found. Checked:")
        for path in DEFAULT_CONFIG_DIRS:
            print(f"  - {os.path.join(path, DEFAULT_CONFIG_FILE)}")
        print(f"\nYou can set the config path with: export {ENV_CONFIG_PATH}=~/path/to/your/config.yaml")


def edit_config():
    """Open the configuration file in the default editor."""
    config_path = get_config_path()
    if not config_path:
        config_dir = ensure_config_dir()
        config_path = os.path.join(config_dir, DEFAULT_CONFIG_FILE)
        create_default_config(config_path)
    
    editor = os.environ.get('EDITOR', 'nano')
    try:
        subprocess.run([editor, config_path], check=True)
    except Exception as e:
        print(f"Error opening editor: {e}")
        sys.exit(1)


def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(
        description='WorkEnv - A tool to automate daily project tasks',
        epilog=f"Config file is searched in: ${{ENV_CONFIG_PATH}}, {', '.join(DEFAULT_CONFIG_DIRS)}"
    )
    
    # Add project management arguments
    project_group = parser.add_argument_group('project execution')
    project_group.add_argument('project', nargs='?', help='Project name to run')
    project_group.add_argument('--action', '-a', help='Specific action to run')
    project_group.add_argument('args', nargs='*', help='Additional arguments to pass to actions')
    
    # Add configuration management arguments
    config_group = parser.add_argument_group('configuration')
    config_group.add_argument('--config', help='Path to custom configuration file')
    config_group.add_argument('--list-projects', '-p', action='store_true', help='List available projects')
    config_group.add_argument('--list-actions', '-l', action='store_true', help='List available actions')
    config_group.add_argument('--show-config', '-s', action='store_true', help='Show current configuration path')
    config_group.add_argument('--edit-config', '-e', action='store_true', help='Edit configuration file')
    
    # Add debugging options
    debug_group = parser.add_argument_group('debugging')
    debug_group.add_argument('--verbose', '-v', action='store_true', help='Enable verbose output')
    debug_group.add_argument('--version', action='store_true', help='Show version information')

    # Parse known args to handle all flags properly
    args, extra_args = parser.parse_known_args()
    
    # Set up logging
    logger = setup_logging(args.verbose)
    
    # Handle version request
    if args.version:
        print(f"{APP_NAME} version 1.0.0")
        return
    
    # Handle configuration management commands
    if args.show_config:
        show_config_path()
        return
    
    if args.edit_config:
        edit_config()
        return
    
    # Load configuration
    try:
        config, config_path = load_config(logger, args.config)
    except Exception as e:
        logger.error(f"Failed to load configuration: {e}")
        sys.exit(1)
    
    # Handle list commands
    if args.list_projects:
        list_projects(config)
        return
    
    if args.list_actions:
        list_actions(config)
        return
    
    # If no project provided, show help
    if not args.project:
        parser.print_help()
        print("\nUse --list-projects to see available projects")
        return
    
    # Combine all regular arguments
    command_args = args.args + extra_args
    
    try:
        # Build context for variable substitution
        context = build_context(config, args.project, command_args, config_path, args.action)
        
        # Run the project or specific action
        success = run_project(args.project, config, context, logger, args.action)
        
        # Exit with appropriate status code
        sys.exit(0 if success else 1)
    except ValueError as e:
        logger.error(str(e))
        sys.exit(1)
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
