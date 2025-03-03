# WorkEnv

WorkEnv - A tool to automate daily project tasks with configurable actions

WorkEnv allows you to define projects and associated actions in a YAML configuration file, then run those actions with a simple command line interface.

## Quick start

First, download and install Python. Version 3.11 (or higher) is required.

Now, you can use the WorkEnv CLI without installation. Just run it with ./workenv to load default configuration and see usage.

```console
./workenv
```

## Usage

After the first run of the application, a default configuration is created, which contains a basic project example.
By default application creates configuration in `.config/workenv/config.yml`.

> [!NOTE]
> You can change default configuration path by canging `$WORKENV_CONFIG_PATH` environment variable.

### 1. Configure workenv project

To create your first project you need to edit `config.yml`

```yml
env:
  PATH: $PATH:$WORKENV_CONFIG/bin
  WORKENV_ACTIVE: 'true'
shell:
  init:
  - source $WORKENV_CONFIG/shell/init.sh
actions:
  cd:
  - exec: cd $project_path
  ls:
  - exec: ls
  git_fetch:
  - exec: git fetch --all
  open:
  - exec: $EDITOR ${args[@]}
  test:
  - exec: ~/Desktop/test.sh
projects:
  example:
    actions:
    - name: cd
    - name: test
    - name: git_fetch
    - name: open
      args: code
    env:
      PROJECT_ROOT: $project.path
    path: ~/Projects/example
```

### 2. Run workenv 

Now you can run workenv with argument `example` to execute project

```console
workenv example
```

Or you can run specific action using

```console
workenv example --action test
```


