"""Resnet networks.

Resnet implementation from official flax examples.
https://github.com/google/flax/blob/main/examples/imagenet/models.py
"""

from functools import partial
from typing import Sequence, Tuple, Any, Callable

from brax.training import distribution
from brax.training import networks
from brax.training import types
from brax.training.types import PRNGKey

import flax
from flax import linen
import jax
import jax.numpy as jp

ModuleDef = Any
ActivationFn = Callable[[jp.ndarray], jp.ndarray]
Initializer = Callable[..., Any]

class ResNetBlock(linen.Module):
  """ResNet block."""

  filters: int
  conv: ModuleDef
  norm: ModuleDef
  act: Callable
  strides: tuple[int, int] = (1, 1)

  @linen.compact
  def __call__(
      self,
      x,
  ):
    residual = x
    y = self.conv(self.filters, (3, 3), self.strides)(x)
    y = self.norm()(y)
    y = self.act(y)
    y = self.conv(self.filters, (3, 3))(y)
    y = self.norm(scale_init=linen.initializers.zeros_init())(y)

    if residual.shape != y.shape:
      residual = self.conv(
          self.filters, (1, 1), self.strides, name='conv_proj'
      )(residual)
      residual = self.norm(name='norm_proj')(residual)

    return self.act(residual + y)


class BottleneckResNetBlock(linen.Module):
  """Bottleneck ResNet block."""

  filters: int
  conv: ModuleDef
  norm: ModuleDef
  act: Callable
  strides: tuple[int, int] = (1, 1)

  @linen.compact
  def __call__(self, x):
    residual = x
    y = self.conv(self.filters, (1, 1))(x)
    y = self.norm()(y)
    y = self.act(y)
    y = self.conv(self.filters, (3, 3), self.strides)(y)
    y = self.norm()(y)
    y = self.act(y)
    y = self.conv(self.filters * 4, (1, 1))(y)
    y = self.norm(scale_init=linen.initializers.zeros_init())(y)

    if residual.shape != y.shape:
      residual = self.conv(
          self.filters * 4, (1, 1), self.strides, name='conv_proj'
      )(residual)
      residual = self.norm(name='norm_proj')(residual)

    return self.act(residual + y)

class ResNet(linen.Module):
  stage_sizes: Sequence[int]
  layer_sizes: Sequence[int]
  block_cls: ModuleDef
  activation: ActivationFn = linen.relu
  kernel_init: Initializer = jax.nn.initializers.lecun_uniform()
  activate_final: bool = False
  bias: bool = True
  layer_norm: bool = False
  num_filters: int = 64
  dtype: Any = jp.float32
  conv: ModuleDef = linen.Conv

  @linen.compact
  def __call__(self, data: jp.ndarray):
    conv = partial(self.conv, use_bias=False, dtype=self.dtype)
    norm = partial(
        linen.BatchNorm,
        use_running_average=False,
        momentum=0.9,
        epsilon=1e-5,
        dtype=self.dtype,
        axis_name='batch',
    )

    hidden = data
    hidden = conv(
        self.num_filters,
        (7, 7),
        (2, 2),
        padding=[(3, 3), (3, 3)],
        name='conv_init',
    )(hidden)
    hidden = norm(name='bn_init')(hidden)
    hidden = linen.relu(hidden)
    hidden = linen.max_pool(hidden, (3, 3), strides=(2, 2), padding='SAME')
    for i, block_size in enumerate(self.stage_sizes):
      for j in range(block_size):
        strides = (2, 2) if i > 0 and j == 0 else (1, 1)
        hidden = self.block_cls(
            self.num_filters * 2**i,
            strides=strides,
            conv=conv,
            norm=norm,
            act=self.activation,
        )(hidden)
    hidden = jp.mean(hidden, axis=(1, 2))

    for i, hidden_size in enumerate(self.layer_sizes):
      hidden = linen.Dense(
          hidden_size,
          kernel_init=self.kernel_init,
          use_bias=self.bias,
          dtype=self.dtype,
      )(hidden)
      if i != len(self.layer_sizes) - 1 or self.activate_final:
        hidden = self.activation(hidden)
        if self.layer_norm:
          hidden = linen.LayerNorm()(hidden)
    
    return hidden

ResNet50 = partial(
    ResNet, stage_sizes=[3, 4, 6, 3], block_cls=BottleneckResNetBlock
)


if __name__ == '__main__':
  rng = jax.random.PRNGKey(0)
  model = ResNet50(layer_sizes=[256, 256], activation=linen.relu)
  params = model.init(rng, jp.ones((1, 64, 64, 4)))

  x = jp.ones((1, 64, 64, 4))
  tabulate_fn = linen.tabulate(model, rng)
  print(tabulate_fn(x))
  print('Resnet50 test passed')