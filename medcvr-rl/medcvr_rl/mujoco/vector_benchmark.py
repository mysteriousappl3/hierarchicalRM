import argparse
import os
import sys
import time
from typing import Tuple

import jax
import jax.numpy as jp
from medcvr_rl.mujoco.envs.pushblock import PushBlock
from medcvr_rl.mujoco.envs.reachtarget import ReachTarget
from medcvr_rl.mujoco.envs.cutrope import CutRope

arg_parser = argparse.ArgumentParser()
arg_parser.add_argument('--num-worlds', type=int, required=True)
arg_parser.add_argument('--num-steps', type=int, required=True)
arg_parser.add_argument('--unroll', type=int, default=1)

args = arg_parser.parse_args()

# Tell XLA to use Triton GEMM
xla_flags = os.environ.get('XLA_FLAGS', '')
xla_flags += ' --xla_gpu_triton_gemm_any=True'
os.environ['XLA_FLAGS'] = xla_flags


def _measure(fn, *args) -> Tuple[float, float]:
  """Reports jit time and op time for a function."""
  beg = time.time()
  compiled_fn = fn.lower(*args).compile()
  end = time.time()
  jit_time = end - beg

  beg = time.time()
  result = compiled_fn(*args)
  jax.block_until_ready(result)
  end = time.time()
  run_time = end - beg

  return jit_time, run_time


def benchmark(env, nstep, batch_size, unroll_steps=1):
  @jax.pmap
  def init(key):
    key = jax.random.split(key, batch_size // jax.device_count())
    return jax.vmap(env.reset)(key)

  key = jax.random.split(jax.random.key(0), jax.device_count())
  d = init(key)
  jax.block_until_ready(d)

  @jax.pmap
  def unroll(d):
    @jax.vmap
    def step(d, _):
      d = env.step(d, jp.zeros(env.sys.nu))
      return d, None

    d, _ = jax.lax.scan(step, d, None, length=nstep, unroll=unroll_steps)

    return d

  jit_time, run_time = _measure(unroll, d)
  steps = nstep * batch_size
  return jit_time, run_time, steps

if __name__ == '__main__':
  env = CutRope()

  jit_time, run_time, steps = benchmark(
      env,
      args.num_steps,
      args.num_worlds,
      unroll_steps=args.unroll)

  print(
    f"""
    Summary for {args.num_worlds} parallel rollouts
    Total JIT time: {jit_time:.2f} s
    Total simulation time: {run_time:.2f} s
    Total steps per second: { steps / run_time:.0f}
    Total realtime factor: { steps * env.sys.opt.timestep / run_time:.2f} x
    Total time per step: { 1e6 * run_time / steps:.2f} µs""")