""" Test a task . """

import numpy as np
import time
import mujoco
import mujoco.viewer

from medcvr_rl.kinematics.utils import quaternion_inverse
from medcvr_rl.kinematics.psm_kinematics import compute_psm_ik, compute_psm_fk, PSMKinematicData

# x y z rx ry rz format
current_command = np.zeros(6)
speed_multiplier = 0.005

def key_callback(keycode):
  if keycode == 262:
    current_command[0] = -1
  if keycode == 263:
     current_command[0] = 1
  if keycode == 265:
    current_command[1] = -1
  if keycode == 264:
    current_command[1] = 1


def main() -> None:
  assert mujoco.__version__ >= "3.1.0", "Please upgrade to mujoco 3.1.0 or later."

  # Assumes we are in the root directory of the repository.
  model = mujoco.MjModel.from_xml_path("descriptions/mujoco_scenes/pushblock.xml")
  data = mujoco.MjData(model)
  kinematics_data = PSMKinematicData()

  # Simulation timestep in seconds.
  dt: float = 0.002

  print("Loaded Models: Model has {} joints and {} dofs.".format(model.njnt, model.nv))

  joint_names = [
    "outer_yaw",
    "outer_pitch",
    "main_insertion",
    "tool_roll",
    "tool_pitch",
    "tool_yaw",
  ]

  actuator_ids = np.array([model.actuator(name).id for name in joint_names])

  key_id = model.key("home").id
  tooltip_id = model.site("tool_tip").id

  # Pre-allocate numpy arrays.
  start_tip_pos = np.zeros(3)
  start_tip_quat = np.zeros(4)
  current_tip_pos = np.zeros(3)
  current_tip_quat = np.zeros(4)
  desired_tip_pos = np.zeros(3)
  desired_tip_quat = np.zeros(4)

  with mujoco.viewer.launch_passive(model=model, data=data, key_callback=key_callback) as viewer:

      mujoco.mj_resetDataKeyframe(model, data, key_id)
      mujoco.mjv_defaultFreeCamera(model, viewer.cam)
      mujoco.mj_kinematics(model, data)

      current_tip_transform = np.array(
         compute_psm_fk([0, 0, 0.12, 0, 0, 0, 0], 7, kinematics_data))
      
      current_tip_pos[:] = current_tip_transform[0:3, 3]
      current_tip_rotmat = current_tip_transform[0:3, 0:3]
      current_tip_rotmat = np.asarray(current_tip_rotmat.flatten())
      mujoco.mju_mat2Quat(current_tip_quat, current_tip_rotmat)

      start_tip_pos[:] = current_tip_pos
      start_tip_quat[:] = current_tip_quat

      while viewer.is_running():
        step_start = time.time()
        
        # Use cartesian increment with current_command
        desired_tip_pos[:] = current_tip_pos + (current_command[0:3] * speed_multiplier)
        desired_tip_quat[:] = current_tip_quat
        current_command[:] = 0

        # convert quat to mat
        desired_tip_rotmat = np.zeros(9)
        mujoco.mju_quat2Mat(desired_tip_rotmat, desired_tip_quat)

        # Compute inverse kinematics.
        current_tip_pose_mat = np.zeros((4, 4))
        current_tip_pose_mat[0:3, 0:3] = np.reshape(desired_tip_rotmat, (3, 3))
        current_tip_pose_mat[0:3, 3] = desired_tip_pos[:]

        current_tip_pos[:] = desired_tip_pos
        current_tip_quat[:] = desired_tip_quat

        q = np.zeros(6)
        q[0:6] = compute_psm_ik(current_tip_pose_mat, kinematics_data)
        data.ctrl[actuator_ids] = q

        mujoco.mj_step(model, data)

        viewer.sync()
        time_until_next_step = dt - (time.time() - step_start)
        if time_until_next_step > 0:
          time.sleep(time_until_next_step)

if __name__ == "__main__":
  main()