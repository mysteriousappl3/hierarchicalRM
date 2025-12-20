import argparse
import functools
import os
import sys
import time
from datetime import datetime
from typing import Optional, Any, List, Sequence, Dict, Tuple, Union, Callable

# FIXME, hacky, but need to leave decent chunk of memory for Madrona /
# the batch renderer
def limit_jax_mem(limit):
    os.environ["XLA_PYTHON_CLIENT_MEM_FRACTION"] = f"{limit:.2f}"
limit_jax_mem(0.1)

# Tell XLA to use Triton GEMM
xla_flags = os.environ.get('XLA_FLAGS', '')
xla_flags += ' --xla_gpu_triton_gemm_any=True'
os.environ['XLA_FLAGS'] = xla_flags

import jax
import jax.numpy as jp
import flax
import numpy as np

from brax.io import html
from brax.io import image
from brax.training.agents.ppo import train as ppo
from mujoco.mjx._src import math
from mujoco.mjx._src import io
from mujoco.mjx._src import support

from medcvr_rl.mujoco.envs.pushblock import VisionPushBlock

from madrona_mjx.viz import VisualizerGPUState, Visualizer

arg_parser = argparse.ArgumentParser()
arg_parser.add_argument('--gpu-id', type=int, default=0)
arg_parser.add_argument('--num-worlds', type=int, required=True)
arg_parser.add_argument('--window-width', type=int, required=True)
arg_parser.add_argument('--window-height', type=int, required=True)
arg_parser.add_argument('--batch-render-view-width', type=int, required=True)
arg_parser.add_argument('--batch-render-view-height', type=int, required=True)
arg_parser.add_argument('--add-cam-debug-geo', action='store_true')
arg_parser.add_argument('--use-raytracer', action='store_true')

args = arg_parser.parse_args()

viz_gpu_state = VisualizerGPUState(args.window_width, args.window_height, args.gpu_id)

if __name__ == '__main__':
  env = VisionPushBlock(
    render_batch_size=args.num_worlds,
    gpu_id=args.gpu_id,
    render_width=args.batch_render_view_width,
    render_height=args.batch_render_view_height,
    add_cam_debug_geo=args.add_cam_debug_geo,
    use_rt=args.use_raytracer,
    render_viz_gpu_hdls=viz_gpu_state.get_gpu_handles())

  jit_env_reset = jax.jit(jax.vmap(env.reset))
  jit_env_step = jax.jit(jax.vmap(env.step))

  # rollout the env
  rollout = []
  rng = jax.random.PRNGKey(seed=2)
  rng, *key = jax.random.split(rng, args.num_worlds + 1)
  state = jit_env_reset(rng=jp.array(key))

  def step_fn(carry):
    rng, state = carry

    act_rng, rng = jax.random.split(rng)
    ctrl = jp.zeros((args.num_worlds, env.sys.nu))
    state = jit_env_step(state, ctrl)

    return rng, state
    
  visualizer = Visualizer(viz_gpu_state, env.renderer.madrona)
  visualizer.loop(env.renderer.madrona, step_fn, (rng, state))
