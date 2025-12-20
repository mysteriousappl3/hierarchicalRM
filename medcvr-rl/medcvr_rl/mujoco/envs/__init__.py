
from typing import Type

from medcvr_rl.mujoco.envs import pushblock
from medcvr_rl.mujoco.envs import rollblock
from medcvr_rl.mujoco.envs import cutrope
from medcvr_rl.mujoco.envs import reachtarget

from brax.envs.base import Env

_envs = {
  'pushblock': pushblock.PushBlock,
  'rollblock': rollblock.RollBlock,
  'cutrope': cutrope.CutRope,
  'reachtarget': reachtarget.ReachTarget
}

def get_environment_class(env_name: str) -> Type[Env]:
  """Returns the class from the environment registry.

  Args:
  env_name: environment name string

  Returns:
  env: an environment class
  """
  return _envs[env_name]

def get_environment(env_name: str, **kwargs) -> Env:
  """Returns an environment from the environment registry.

  Args:
  env_name: environment name string
  **kwargs: keyword arguments that get passed to the Env class constructor

  Returns:
  env: an environment
  """
  return _envs[env_name](**kwargs)


def register_environment(env_name: str, env_class: Type[Env]):
  """Adds an environment to the registry.

  Args:
  env_name: environment name string
  env_class: the Env class to add to the registry
  """
  _envs[env_name] = env_class