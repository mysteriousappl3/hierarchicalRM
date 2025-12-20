import os
from datetime import datetime
import jax
from jax import numpy as jp
import numpy as np
from typing import Any, Dict, Sequence, Tuple, Union

from brax import base
from brax import envs
from brax import math
from brax.base import Base, Motion, Transform
from brax.envs.base import Env, PipelineEnv, State
from brax.io import html, mjcf, model

import mujoco
from mujoco import mjx

from madrona_mjx.renderer import BatchRenderer

from medcvr_rl.kinematics.psm_kinematics_jax import compute_psm_fk, compute_psm_ik

class RollBlock(PipelineEnv):

  def __init__(
    self,
    vision_obs=False,
    x_spawn_range=(-0.08, 0.08),
    y_spawn_range=(-0.07, 0.06),
    distance_reward_weight=1.25,
    goal_reward=5.0,
    render_batch_size=16,
    gpu_id=0,
    render_width=64,
    render_height=64,
    enabled_geom_groups=np.array([0, 1, 2]),
    add_cam_debug_geo=False,
    use_rt: bool = False,
    render_viz_gpu_hdls=None,
    **kwargs,):
    mj_model = mujoco.MjModel.from_xml_path('descriptions/mujoco_scenes/mjx_pushblock.xml')
    mj_model.opt.solver = mujoco.mjtSolver.mjSOL_CG
    mj_model.opt.iterations = 10
    mj_model.opt.ls_iterations = 10

    sys = mjcf.load_model(mj_model)

    physics_steps_per_control_step = 5
    kwargs['n_frames'] = kwargs.get(
      'n_frames', physics_steps_per_control_step)
    kwargs['backend'] = 'mjx'

    super().__init__(sys, **kwargs)

    self._distance_reward_weight = distance_reward_weight
    self._goal_reward = goal_reward
    self._x_spawn_range = x_spawn_range
    self._y_spawn_range = y_spawn_range

    self._start_q = [0, 0, 0.115, 0, 0, 0]
    self._start_tiptransform = compute_psm_fk(self._start_q)
    self._speed_multiplier = 0.005


    self._goal_pos = mj_model.geom_pos[mj_model.geom('goal').id]
    self._tooltip_id = mj_model.site('tool_tip').id
    self._block_id = mj_model.body('block').id
    self._base_id = mj_model.body('base_link').id

    self._vision_obs = vision_obs
    if vision_obs:
      self.renderer = BatchRenderer(
        sys, gpu_id, render_batch_size, render_width, render_height, 
        enabled_geom_groups, add_cam_debug_geo, use_rt, render_viz_gpu_hdls)
  
  @property
  def action_size(self) -> int:
    return 2

  def reset(self, rng: jp.ndarray) -> State:
    """Resets the environment to an initial state."""
    rng, rng1, rng2 = jax.random.split(rng, 3)

    x = jax.random.uniform(
      rng1, (1,),
      minval=self._x_spawn_range[0],
      maxval=self._x_spawn_range[1])      
    y = jax.random.uniform(
      rng1, (1,),
      minval=self._y_spawn_range[0],
      maxval=self._y_spawn_range[1])

    qpos = self.sys.qpos0
    qpos = qpos.at[4].set(0.115)
    qpos = qpos.at[12].set(x[0])
    qpos = qpos.at[13].set(y[0])
    qvel = jp.zeros(self.sys.nv)
    pipeline_state = self.pipeline_init(qpos, qvel)

    current_transform = compute_psm_fk(self._start_q)

    reward, done, zero = jp.zeros(3)
    metrics = {
      'distance_reward': zero,
      'goal_reward': zero,
      'x_position': zero,
      'y_position': zero,
    }

    if self._vision_obs:
      render_token, rgb, depth = self.renderer.init(pipeline_state)
      obs = jp.asarray(rgb[0], dtype=jp.float32) / 255.0
      info = {
        'render_token': render_token,
        'rgb': rgb[0],
        'depth': depth[0],
        'current_pos' : current_transform[:3, 3]
      }
    else:
      obs = self._get_obs(pipeline_state, jp.zeros(self.sys.nu))
      info = {
        'current_pos' : current_transform[:3, 3]
      }

    return State(pipeline_state, obs, reward, done, metrics, info)

  def step(self, state: State, action: jp.ndarray) -> State:
    """Runs one timestep of the environment's dynamics."""
    data0 = state.pipeline_state

    new_tipposition = state.info['current_pos']
    scaled_action = action * self._speed_multiplier
    new_tipposition = new_tipposition.at[:2].add(action)
    new_tipposition = jp.clip(new_tipposition, -0.17, 0.17)

    current_tippose = self._start_tiptransform
    current_tippose = current_tippose.at[:3, 3].set(new_tipposition)
    jointpos = compute_psm_ik(current_tippose)
    jointpos_withjaw = jp.append(jointpos, 0)
    data = self.pipeline_step(data0, jointpos_withjaw)

    state.info.update({'current_pos': new_tipposition})

    distance_reward = 1 - (6 * jp.abs(data.q[13] - 0.08))
    goal_reached = jp.where(data.q[13] > 0.08, 1.0, 0.0)
    goal_reward = goal_reached * self._goal_reward

    if self._vision_obs:
      _, rgb, depth = self.renderer.render(state.info['render_token'], data)
      state.info.update({'rgb': rgb[0], 'depth': depth[0]})
      obs = jp.asarray(rgb[0], dtype=jp.float32) / 255.0
    else:
      obs = self._get_obs(data, action)

    reward = goal_reward
    done = goal_reached

    state.metrics.update(
      distance_reward=distance_reward,
      goal_reward=goal_reward,
      x_position=data.q[12],
      y_position=data.q[13]
    )

    return state.replace(
      pipeline_state=data, obs=obs, reward=reward, done=done, info=state.info)

  def _get_obs(self, data: mjx.Data, action: jp.ndarray) -> jp.ndarray:
    """Observes humanoid body position, velocities, and angles."""
    tooltip_to_goal = self._goal_pos - data.site_xpos[self._tooltip_id]
    tooltip_to_block = data.xpos[self._block_id] - data.site_xpos[self._tooltip_id]
    goal_to_block = data.xpos[self._block_id] - self._goal_pos

    # external_contact_forces are excluded
    return jp.concatenate([
      tooltip_to_goal,
      tooltip_to_block,
      goal_to_block
    ])