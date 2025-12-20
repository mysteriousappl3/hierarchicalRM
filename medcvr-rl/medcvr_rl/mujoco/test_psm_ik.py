""" Test the PSM IK controller in Mujoco. """

import numpy as np
import time
import mujoco
import mujoco.viewer

from medcvr_rl.kinematics.utils import quaternion_inverse
from medcvr_rl.kinematics.psm_kinematics import compute_ik, compute_fk, PSMKinematicData

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

  # key_id = model.key("home").id
  mocap_id = model.body("target").mocapid[0]
  baselink_id = model.body("base_link").id
  tooltip_id = model.site("tool_tip").id

  # Pre-allocate numpy arrays.
  base_link_pos = np.zeros(3)
  base_link_quat = np.zeros(4)
  inv_base_link_pos = np.zeros(3)
  inv_base_link_quat = np.zeros(4)
  current_tip_pos_bf = np.zeros(3)
  current_tip_quat_bf = np.zeros(4)
  current_tip_pos_wf = np.zeros(3)
  current_tip_quat_wf = np.zeros(4)

  with mujoco.viewer.launch_passive(
      model=model, data=data, show_left_ui=True, show_right_ui=True
    ) as viewer:

      # mujoco.mj_resetDataKeyframe(model, data, key_id)
      mujoco.mjv_defaultFreeCamera(model, viewer.cam)
      mujoco.mj_kinematics(model, data)

      current_tip_pose_mat = np.array(compute_fk([0, 0, 0.1, 0, 0, 0, 0], 7, kinematics_data))
      current_tip_pos_bf = current_tip_pose_mat[0:3, 3]
      current_tip_rot_mat = current_tip_pose_mat[0:3, 0:3]
      current_tip_rot_mat = np.asarray(current_tip_rot_mat.flatten())
      mujoco.mju_mat2Quat(current_tip_quat_bf, current_tip_rot_mat)

      # Transform from base frame to world frame.
      base_link_pos[:] = data.xpos[baselink_id]
      base_link_quat[:] = data.xquat[baselink_id]
      inv_base_link_rot = quaternion_inverse(base_link_quat)
      inv_base_link_pos = np.zeros(3)
      mujoco.mju_rotVecQuat(inv_base_link_pos, base_link_pos, inv_base_link_rot)
      inv_base_link_pos = -inv_base_link_pos

      tmp = np.zeros(3)
      mujoco.mju_rotVecQuat(tmp, current_tip_pos_bf, base_link_quat)
      current_tip_pos_wf = base_link_pos + tmp
      mujoco.mju_mulQuat(current_tip_quat_wf, base_link_quat, current_tip_quat_bf)

      data.mocap_pos[mocap_id] = current_tip_pos_wf
      data.mocap_quat[mocap_id] = current_tip_quat_wf

      while viewer.is_running():
        step_start = time.time()

        # Position error.
        desired_tip_pos_wf = data.mocap_pos[mocap_id]

        # Convert base frame to world frame
        x = np.zeros(3)
        mujoco.mju_rotVecQuat(x, desired_tip_pos_wf, inv_base_link_quat)
        desired_tip_pos_bf = inv_base_link_pos + x

        # Compute inverse kinematics.
        current_tip_pose_mat[0:3, 3] = desired_tip_pos_bf
        q = np.zeros(6)
        q[0:6] = compute_ik(current_tip_pose_mat, kinematics_data)

        # Step the simulation.
        data.ctrl[actuator_ids] = q

        mujoco.mj_step(model, data)

        viewer.sync()
        time_until_next_step = dt - (time.time() - step_start)
        if time_until_next_step > 0:
          time.sleep(time_until_next_step)

if __name__ == "__main__":
  main()