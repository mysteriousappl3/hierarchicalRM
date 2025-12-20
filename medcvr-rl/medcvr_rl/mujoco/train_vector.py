import argparse
import os
import functools

from matplotlib import pyplot as plt

import jax
from brax.training.agents.ppo import train as ppo

arg_parser = argparse.ArgumentParser()
arg_parser.add_argument('--env', type=str, required=True, 
  choices=['pushblock', 'rollblock'])
arg_parser.add_argument('--num-worlds', type=int, required=True)
args = arg_parser.parse_args()

# Tell XLA to use Triton GEMM
xla_flags = os.environ.get('XLA_FLAGS', '')
xla_flags += ' --xla_gpu_triton_gemm_any=True'
os.environ['XLA_FLAGS'] = xla_flags


if __name__ == '__main__':
  env_module = __import__(f"medcvr_rl.mujoco.envs.{args.env}", fromlist=[''])

  class_names = {
    'pushblock': 'PushBlock',
    'rollblock': 'RollBlock'
  }
  env_module = getattr(env_module, class_names[args.env])
  env = env_module()

  train_fn = functools.partial(
    ppo.train, num_timesteps=10_000_000, num_evals=5, reward_scaling=0.1,
    episode_length=1000, normalize_observations=True, action_repeat=1,
    unroll_length=10, num_minibatches=32, num_updates_per_batch=8,
    discounting=0.97, learning_rate=3e-4, entropy_cost=1e-3,
    num_envs=args.num_worlds, batch_size=1024, seed=0)

  def progress(num_steps, metrics):
    print(f'step: {num_steps}, reward: {metrics["eval/episode_reward"]}')
  
  make_inference_fn, params, _= train_fn(environment=env, progress_fn=progress)
  jit_inference_fn = jax.jit(make_inference_fn(params))