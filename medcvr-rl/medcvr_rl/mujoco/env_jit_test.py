import argparse
import os
import sys
import time
from typing import Tuple

import jax
import jax.numpy as jp
from matplotlib import pyplot as plt

from medcvr_rl.mujoco.envs.pushblock import VisionPushBlock
from medcvr_rl.mujoco.envs.reachtarget import VisionReachTarget

arg_parser = argparse.ArgumentParser()
arg_parser.add_argument('--gpu-id', type=int, default=0)
arg_parser.add_argument('--num-worlds', type=int, required=True)
arg_parser.add_argument('--batch-render-view-width', type=int, default=64)
arg_parser.add_argument('--batch-render-view-height', type=int, default=64)
arg_parser.add_argument('--use-raytracer', action='store_true')

args = arg_parser.parse_args()


# FIXME, hacky, but need to leave decent chunk of memory for Madrona /
# the batch renderer
def limit_jax_mem(limit):
    os.environ["XLA_PYTHON_CLIENT_MEM_FRACTION"] = f"{limit:.2f}"
limit_jax_mem(0.15)

# Tell XLA to use Triton GEMM
xla_flags = os.environ.get('XLA_FLAGS', '')
xla_flags += ' --xla_gpu_triton_gemm_any=True'
os.environ['XLA_FLAGS'] = xla_flags

if __name__ == '__main__':
  env = VisionPushBlock(
    render_batch_size=args.num_worlds,
    gpu_id=args.gpu_id,
    render_width=args.batch_render_view_width,
    render_height=args.batch_render_view_height,
    use_rt=args.use_raytracer,)

  rng = jax.random.PRNGKey(0)
  reset_fn = jax.jit(jax.vmap(env.reset))
  rng, step_rng = jax.random.split(rng, 2)
  mjx_state = reset_fn(jax.random.split(step_rng, args.num_worlds))

  step_fn = jax.jit(jax.vmap(env.step))
  act = jax.random.uniform(rng, (args.num_worlds, 2), minval=-1.0, maxval=1.0)
  mjx_state = step_fn(mjx_state, act)

  print(mjx_state.obs.shape)
  plt.imshow(mjx_state.obs[0])
  plt.show()
  
