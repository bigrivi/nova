# Code Execution

## `code_run`

Execute Python code inline. Nova spawns a subprocess, runs the code, and returns
stdout and stderr.

```text
Calculate the first 20 Fibonacci numbers using Python
```

The code is displayed with Python syntax highlighting in the frontend.

## Custom Packages

Nova automatically installs required packages on demand to
`~/.nova/site-packages/`. If the code imports a package that isn't installed,
Nova asks whether to install it.

## Desktop Builds

In PyInstaller-packaged desktop builds, `code_run` uses the host system's Python
rather than the bundled interpreter.
