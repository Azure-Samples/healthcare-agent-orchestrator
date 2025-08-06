# Jupyter Notebooks Setup Guide

This guide helps you set up Jupyter to run the notebooks in this repository.

## Quick Setup (Recommended)

1. **Activate venv**

    ```bash
    source .venv/bin/activate
    ```

1. **Install dependencies:**

   ```bash
   cd src
   export SCENARIO=default
   pip install -r requirements.txt
   pip install -r requirements-eval.txt
   ```

1. **Set up Jupyter kernel for VS Code:**

   ```bash
   python -m ipykernel install --user --name "healthcare-agent-orchestrator" --display-name "Healthcare Agent Orchestrator"

1. **az login in venv:**
   ```bash
   az login
   ```

## Running Notebooks

### Option 1: VS Code (Recommended)

1. Open the project in VS Code
2. Install the Jupyter extension if not already installed
3. Open any `.ipynb` file in the `notebooks/` directory
4. Select the "Healthcare Agent Orchestrator" kernel when prompted

### Option 2: Jupyter Lab/Notebook

1. Make sure your environment is activated (if using one):

   ```bash
   source .venv/bin/activate  # or your preferred venv path
   ```

2. Start Jupyter:

   ```bash
   jupyter notebook notebooks/
   ```

## Troubleshooting

- **ImportError**: Make sure you've installed the main project dependencies (`pip install -r src/requirements.txt`)
- **Azure Authentication**: Ensure you're logged into Azure CLI: `az login`
- **Missing .env**: Generated during infrastructure deployment
- **Python Version**: Requires Python 3.8 or later
