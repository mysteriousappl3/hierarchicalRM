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
from brax.mjx.base import State as MjxState
from brax.training.agents.ppo import train as ppo
from brax.training.agents.ppo import networks as ppo_networks
from brax.io import html, mjcf, model

import mujoco
from mujoco import mjx

from madrona_mjx.renderer import BatchRenderer

from medcvr_rl.kinematics.psm_kinematics_jax import compute_psm_fk, compute_psm_ik

class ReachTarget(PipelineEnv):

  def __init__(
    self,
    x_spawn_range=(-0.08, 0.08),
    y_spawn_range=(-0.07, 0.06),
    distance_reward_weight=1.25,
    goal_reward=5.0,
    **kwargs,):
    mj_model = mujoco.MjModel.from_xml_path('descriptions/mujoco_scenes/mjx_reachtarget.xml')
    mj_model.opt.solver = mujoco.mjtSolver.mjSOL_CG
    mj_model.opt.iterations = 6
    mj_model.opt.ls_iterations = 6

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

  def reset(self, rng: jp.ndarray) -> State:
    """Resets the environment to an initial state."""
    rng, rng1, rng2 = jax.random.split(rng, 3)

    qpos = self.sys.qpos0
    qpos = qpos.at[4].set(0.115)
    qvel = jp.zeros(self.sys.nv)
    pipeline_state = self.pipeline_init(qpos, qvel)

    current_transform = compute_psm_fk(self._start_q)

    obs = self._get_obs(pipeline_state, jp.zeros(self.sys.nu))
    reward, done, zero = jp.zeros(3)
    metrics = {
    }
    info = {
      'current_pos' : current_transform[:3, 3]
    }

    return State(pipeline_state, obs, reward, done, metrics, info)

  def step(self, state: State, action: jp.ndarray) -> State:
    """Runs one timestep of the environment's dynamics."""
    data0 = state.pipeline_state

    new_tipposition = state.info['current_pos']
    scaled_action = action * self._speed_multiplier
    # new_tipposition = new_tipposition.at[:2].add(action)
    new_tipposition = jp.clip(new_tipposition, -0.17, 0.17)

    current_tippose = self._start_tiptransform
    current_tippose = current_tippose.at[:3, 3].set(new_tipposition)
    jointpos = compute_psm_ik(current_tippose)
    jointpos_withjaw = jp.append(jointpos, 0)
    data = self.pipeline_step(data0, jointpos_withjaw)

    state.info['current_pos'] = new_tipposition

    reward, done, zero = jp.zeros(3)
    obs = self._get_obs(data, action)

    return state.replace(
      pipeline_state=data, obs=obs, reward=reward, done=done, info=state.info)

  def _get_obs(self, data: mjx.Data, action: jp.ndarray) -> jp.ndarray:
    """Observes humanoid body position, velocities, and angles."""
    return jp.array([0.0])


class VisionReachTarget(PipelineEnv):
  def __init__(
    self,
    render_batch_size=16,
    gpu_id=0,
    render_width=64,
    render_height=64,
    add_cam_debug_geo=False,
    use_rt: bool = False,
    render_viz_gpu_hdls=None,
    x_spawn_range=(-0.08, 0.08),
    y_spawn_range=(-0.07, 0.06),
    distance_reward_weight=1.25,
    goal_reward=5.0,
    **kwargs,):
    mj_model = mujoco.MjModel.from_xml_path('descriptions/mujoco_scenes/mjx_reachtarget.xml')
    mj_model.opt.solver = mujoco.mjtSolver.mjSOL_CG
    mj_model.opt.iterations = 6
    mj_model.opt.ls_iterations = 6

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

    # Madrona renderer
    self.renderer = BatchRenderer(
      sys, gpu_id, render_batch_size, render_width, render_height, add_cam_debug_geo,
      use_rt, render_viz_gpu_hdls)

  def reset(self, rng: jp.ndarray) -> State:
    """Resets the environment to an initial state."""
    rng, rng1, rng2 = jax.random.split(rng, 3)

    qpos = self.sys.qpos0
    qpos = qpos.at[4].set(0.115)
    qvel = jp.zeros(self.sys.nv)
    pipeline_state = self.pipeline_init(qpos, qvel)

    current_transform = compute_psm_fk(self._start_q)

    obs = self._get_obs(pipeline_state, jp.zeros(self.sys.nu))
    reward, done, zero = jp.zeros(3)
    metrics = {
    }
    info = {
      'current_pos' : current_transform[:3, 3]
    }

    render_token, rgb, depth = self.renderer.init(pipeline_state)
    info.update({'render_token': render_token, 'rgb': rgb, 'depth': depth})

    return State(pipeline_state, obs, reward, done, metrics, info)

  def step(self, state: State, action: jp.ndarray) -> State:
    """Runs one timestep of the environment's dynamics."""
    data0 = state.pipeline_state

    new_tipposition = state.info['current_pos']
    scaled_action = action * self._speed_multiplier
    # new_tipposition = new_tipposition.at[:2].add(action)
    new_tipposition = jp.clip(new_tipposition, -0.17, 0.17)

    current_tippose = self._start_tiptransform
    current_tippose = current_tippose.at[:3, 3].set(new_tipposition)
    jointpos = compute_psm_ik(current_tippose)
    jointpos_withjaw = jp.append(jointpos, 0)
    data = self.pipeline_step(data0, jointpos_withjaw)

    state.info['current_pos'] = new_tipposition

    reward, done, zero = jp.zeros(3)
    obs = self._get_obs(data, action)
    
    _, rgb, depth = self.renderer.render(state.info['render_token'], data)
    state.info.update({'rgb': rgb, 'depth': depth})

    return state.replace(
      pipeline_state=data, obs=obs, reward=reward, done=done, info=state.info)

  def _get_obs(self, data: mjx.Data, action: jp.ndarray) -> jp.ndarray:
    """Observes humanoid body position, velocities, and angles."""
    return jp.array([0.0])

