# dVRK ML Agents

## Installation

### Anaconda
We prefer to use anaconda when dealing with python + machine learning. Miniconda is preferred as it is a lightweight version of anaconda. 

Miniconda can be installed by following the instructions at: [Miniconda Installation](https://docs.conda.io/projects/miniconda/en/latest/). For a faster experience, you can try Mamba which is a fast C++ implementation of Conda.

After that create a new environment with python 3.10.12

```bash
# Choose whichever environment name suits you
conda create -n mlagents python=3.10.12 # ml-agents only supports specific versions of python
```

You are able to pip install and conda install any package, start with conda install, and use pip install if the package is not available on any conda channels

### ML-Agents and PyTorch
We currently use a locally installed ml-agents rather than the package repository. Follow these instructions to get ml-agents up and running with PyTorch.

```bash
# Install the latest PyTorch version, use the PyTorch website for the latest snippet
# Here we show the anaconda install snippet for cuda 11.8
conda install pytorch torchvision torchaudio pytorch-cuda=11.8 -c pytorch -c nvidia

# Clone the latest stable mlagents repository
# Clone this outside the medcvr_rl repo, right beside where medcvr-rl is located
git clone https://github.com/Unity-Technologies/ml-agents.git

# After cloning, visit ml-agents/ml-agents/setup.py, and from the PyTorch requirements remove <1.9.0 on Line 71/71, otherwise PyTorch will install again as ours will be a higher version.
cd ml-agents
pip install -e ./ml-agents-envs
pip install -e ./ml-agents

cd ../medcvr_rl
pip install -e .
```

### Using ML-Agents in Unity (New Project)
Inside your unity project, you can now add the ml-agents package using the package manager. Click on `+`, then `Add package from disk`, and navigate to the `com.unity.ml-agents` folder inside `ml-agents`, and choose `package.json`. This will install ml-agents inside Unity.

For example projects to test the installation, there are sample projects in the ml-agents repo /ml-agents/Project/Assets/ML-Agents/Examples/. Instructions can be found [here](https://github.com/Unity-Technologies/ml-agents/blob/release_18_docs/docs/Learning-Environment-Executable.md).
