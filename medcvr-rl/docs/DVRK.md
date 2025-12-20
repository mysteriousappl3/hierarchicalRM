# ROS and dVRK

## Installation

### ROS + dVRK Framework

The dVRK Framework from JHU provides full system access to both the physical robot as well as additional software features. Follow these instructions below to get the system up and running.

1. Install [ROS Noetic Install Instruction](http://wiki.ros.org/noetic/Installation/Ubuntu) for Ubuntu 20.04

2. Install dVRK Framework and create catkin_ws following the official [Instructions](https://github.com/jhu-dvrk/sawIntuitiveResearchKit/wiki/CatkinBuild)
    1. Make sure to add devel/setup.bash to ~./bashrc or be prepared to source in new terminals when ROS packages are not found

3. For Unity integration, install ROS-TCP-Endpoint in your catkin_ws:
```bash
cd ~/catkin_ws/src/
git clone https://github.com/Unity-Technologies/ROS-TCP-Endpoint.git
catkin build
```
The ROS-TCP-Endpoint will allow for communication between Unity and ROS, thus allowing communication with the dVRK framework.

4. Add your hostname (found using hostname -I) to the config of ROS-TCP-Endpoint at ROS-TCP-Endpoint\config\params.yaml 

5. The PSM can be simulated using a config file, we provide a config file in `dvrk_mlagents\misc\console-PSM2_KIN_SIMULATED.json`. Launch an rviz simulation (not necessary but helps to debug having both simulations running) using the command 

```
roscd dvrk_config
roslaunch dvrk_robot dvrk_arm_rviz.launch arm:=PSM2 config:=PATH/TO/CONFIG/FOLDER/console-PSM2_KIN_SIMULATED.json 
```

6. An rviz simulation and the dvrk console should launch. If one or the other does not launch there is a problem. The dVRK console is the main hub for all communication.


### Unity ROS Connection
1. Install Unity Hub, and the latest version of Unity (2021.X, older versions are missing physics features)

2. Clone the dVRK Unity Sim project, it has a template scene ready to go to test a ROS connection with the dVRK. Open the `dvrk` scene.

3. The Unity scenes require two packages:

- `ROS-TCP-Connector`: Allows for the connector component that is inside the Unity editor to connect Unity to ROS. The package can be added through the package manager through git-url using: `https://github.com/Unity-Technologies/ROS-TCP-Connector.git?path=/com.unity.robotics.ros-tcp-connector`

`URDF-Importer`: Importer made by the Unity Robotics team to import URDF files into unity. The original importer does not support mimic joints, and the PSM has certain mimic joints that need to follow the movements of their paired active joint. We have forked and adapted the URDF-Importer to include control scripts for mimic joints, found under the branch feature/mimic_joints. The package can be added through the package manager through git-url using: `https://github.com/radianag/URDF-Importer.git?path=/com.unity.robotics.urdf-importer#feature/mimic_joints`

3. At the top of the Unity editor there is a toolbar option for Robotics -> ROS Settings once you install the ROS-TCP-Connector. Set the 'ROS IP Address' to the same as the hostname IP that was set in the config/params.yaml file

4. To start the connection between ROS and Unity, run in a seperate terminal the command: `roslaunch ros_tcp_endpoint endpoint.launch`

5. If the command is not found, or there is a python error, install numpy and rospkg (preferably using Anaconda). Install other packages as needed.


### Python API

When using Anaconda, PyKDL needs to be installed. In some cases this step is not neccessary, run the test script below to find out what is needed.

There is a python test file in this repo (copied from the original test file in dvrk_python): `python3 dvrk_mlagents/scripts/test.py -a PSM2`

It should cause the dVRK to move in an orchestrated dance. Use it to debug and test if everything is working. 

To install PyKDL:

1. Clone the kdl library and python bindings from `https://github.com/orocos/orocos_kinematics_dynamics`

2. Follow the steps inside both the Install.md files provided to install the necessary prerequisites

3. Initialize the submodules as mentioned in their instructions

4. Move both orocos_kdl and python_orocos_kdl to catkin_ws alongside the dvrk

5. Run `catkin build`

6. This should install both, you may need to install empy `pip install empy` or other related dependencies

7. Source the new setup.bash (or restart the terminal if you are automatically sourcing)


### dVRK in Unity

To import the dVRK, simply copy over the `dvrk_sim` folder found inside the `Assets` folder of `medcvr-unity\dvrk_sim`. It contains all the necessary prefabs, scripts, models, and more to work with the dVRK. Instructions and explanations can be found in the [dVRK Sim Project](https://mcsscm.utm.utoronto.ca/medcvr/medcvr-unity/-/tree/dev/dvrk_sim).
