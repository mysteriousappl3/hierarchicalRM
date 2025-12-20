# dVRK Reinforcement Learning (RL)

<!-- Badges and Shields -->
![Unity](https://img.shields.io/badge/unity-6-brightgreen)

Unity project for training surgical robotics tasks using ML-Agents.

## Getting Started

### Installation

#### Unity
Installation of the latest version of Unity, version 2021.2.X, is required. The latest version of Unity has the necessary physics features needed for our projects, as well as some specific requirements for the `Obi` package.

To install Unity, install the [Unity Hub](https://unity3d.com/get-unity/download). Once the hub is installed, install the latest version of the Unity 6 editor.
- NOTE: We currently support Unity 6, installing an older version might work, but will cause changes to the project.
- For Linux, the Unity Hub can be installed through `sudo apt-get install`. Instructions can be found [here](https://docs.unity3d.com/hub/manual/InstallHub.html#install-hub-linux).
- Once Unity is installed, clone this repository, and `Add` any of the project folders in the Unity Hub - Projects page. Choose the version of Unity you installed.
- Unity will generate additional files when opening a project, and modify some of the source files to indicate your version of Unity. We have included a .gitignore at the base of each project to avoid pushing these user specific files, but you will need to make sure yourself that you do not push anything user-specific.


#### Editor in Linux

For Linux, we use Visual Studio Code to edit Unity C# files. To get Intellisense to correctly work, follow the following [instructions](docs/EDITOR.md)

### How To Use

TODO: Rework these sections

ML-Agents can be learned quite quickly by following the tutorials and examples from the ml-agents wiki. The PSM prefabs can be used to quickly get the PSM up and running, they come from the `dvrk_sim` project in `medcvr-unity`. The template scene found in `PushBlock` provides an example of how the scene can be set up to accomplish a task.

To train a task, execute the following script from the `dvrk_mlagents` folder (Executing from here will correctly place the results and find the relative path of the config)
```bash
mlagents-learn config\ppo\s2rpushblock_imitation.yaml --run-id=pushblock_s2r_run0 ## For in-editor training
```
Additionally, ML-Agents can be run using multiple instances, following the instructions fround [here](https://github.com/Unity-Technologies/ml-agents/blob/main/docs/Learning-Environment-Executable.md). The benefit here is that a single instance can have parallel environments in the scene, but the single instance will evenetually be bottle-becked by the main thread update. A second instance would have its own main-thread, and so the bottlenecks can be distributed.

#### Control

The `IKPsmController` extends the basic `PSMController` that is part of the `dvrk_sim` project. It allows for control of the PSM using just the tip location. The countinous control can be mapped to a tip delta position by putting a speed modifier.

Direct joint space control is also possible, although may require more training time.

#### Obi Physics

Some of the soft object scenes use the Obi package. Some important information and insights regarding usage can be [found here](docs/obi.md).

## Importing Robots
We use the Unity URDF-Importer to import robots into Unity. Our fork of the URDF-Importer has additional logic handling mimic joints. To import a robot:
1. Find the .urdf file inside unity (The urdf file and related meshes must all be inside Unity's Assets/ folder)
2. Right click to open the context menu, and choose 'Import Robot From Selected URDF File'
3. There will be a prompt to choose the root folder, in our case the root is Assets/Robots/Descriptions/ as all our mesh files are relative to this root
4. If the robot spawns with meshes orientated the wrong way, first try to import again with a different Axis settings (Y vs Z). If this does not work, or only some of the meshes are not oriented correctly, then simple rotate the meshes and collision meshes that are incorrect manually

### Sim2Real 

TODO: Add Sim2real

## Contributing 
Please read [CONTRIBUTING.md](https://github.com/404) for details on our guide to contributing and merge requests.

## Authors 

- **Mustafa Haiderbhai** - mhaid@cs.toronto.edu


See also the list of [contributors](https://github.com/404) who participated in this project.

