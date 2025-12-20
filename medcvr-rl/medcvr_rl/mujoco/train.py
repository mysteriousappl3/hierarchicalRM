import argparse
import os
import time
import functools


from matplotlib import pyplot as plt

import jax
from brax.training.agents.ppo import train as ppo
from brax.training.agents.ppo import networks as ppo_networks

from medcvr_rl.mujoco import envs
from medcvr_rl.mujoco import vision_ppo

arg_parser = argparse.ArgumentParser()
arg_parser.add_argument('--env', type=str, required=True)
arg_parser.add_argument('--vision', action='store_true')
arg_parser.add_argument('--num-worlds', type=int, required=True)
arg_parser.add_argument('--gpu-id', type=int, default=0)
arg_parser.add_argument('--batch-render-view-width', type=int, default=64)
arg_parser.add_argument('--batch-render-view-height', type=int, default=64)
arg_parser.add_argument('--use-raytracer', action='store_true')

args = arg_parser.parse_args()


# FIXME, hacky, but need to leave decent chunk of memory for Madrona /
# the batch renderer
def limit_jax_mem(limit):
    os.environ["XLA_PYTHON_CLIENT_MEM_FRACTION"] = f"{limit:.2f}"

# Tell XLA to use Triton GEMM
xla_flags = os.environ.get('XLA_FLAGS', '')
xla_flags += ' --xla_gpu_triton_gemm_any=True'
os.environ['XLA_FLAGS'] = xla_flags


if __name__ == '__main__':

  env_cls = envs.get_environment_class(args.env)
  
  if args.vision:
    limit_jax_mem(0.6)
    env = env_cls(
      vision_obs=True,
      render_batch_size=args.num_worlds,
      gpu_id=args.gpu_id,
      render_width=args.batch_render_view_width,
      render_height=args.batch_render_view_height,
      use_rt=args.use_raytracer)
  else: 
    env = env_cls()

  # function args
  if args.vision:
    network_factory = vision_ppo.make_vision_ppo_networks
    num_eval_envs = args.num_worlds
    batch_size = 128
  else:
    network_factory = ppo_networks.make_ppo_networks
    num_eval_envs = 128
    batch_size = 1024

  train_fn = functools.partial(
    ppo.train, num_timesteps=10_000_000, num_evals=5, reward_scaling=0.1,
    episode_length=1000, normalize_observations=True, action_repeat=1,
    unroll_length=10, num_minibatches=16, num_updates_per_batch=8,
    discounting=0.97, learning_rate=3e-4, entropy_cost=1e-3,
    num_envs=args.num_worlds, num_eval_envs=num_eval_envs,
    batch_size=batch_size, seed=0, network_factory=network_factory)

  def progress(num_steps, metrics):
    print(f'step: {num_steps}, reward: {metrics["eval/episode_reward"]}')
  
  start = time.time()
  make_inference_fn, params, metrics = train_fn(environment=env, progress_fn=progress)
  end = time.time()
  train_time = end - start

  # jit_inference_fn = jax.jit(make_inference_fn(params))

  print(metrics)
  print(
    f"""
    Summary for {args.env} gpu training
    Total simulation time: {train_time:.2f} s
    Total time per step: { 1e6 * train_time / 10_000_000:.2f} µs""")