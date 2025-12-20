#!/usr/bin/env python3
import pandas as pd
import numpy as np
import seaborn as sns

import matplotlib.pyplot as plt
import matplotlib as mpl

data = [
  0.675,0.25,0.8,0.975,0.575,0.95,0.55,0.5,0.875,0.525,0.8,0.75,0.5,0.875,0.575,
  0.825,0.5,0.5,0.3,0.025,0.2,0.025,0.225,0.275,0.3,0.225,0.3,0.025,0.475,0.4,
  0.275,0.375,0.15,0.65,0.025,0.55,0.625,0.8,0.55,0.4,0.475,0.075,0.025,0.875,
  0.775,0.75,0.225,0.85,0.975,0.025,0.025,0.025,0.525,0.025,0.225,0.625,0.025,0.4
]

def main():

  values = {}

  for val in data:
    if val in values.keys():
      values[val] += 1
    else:
      values[val] = 1
  
  print(values)


  sns.scatterplot(x=values.keys(), y=np.zeros_like(values.keys), size=values.values(), hue=values.values(), palette='crest')
  plt.tight_layout()
  plt.savefig('cutloc.png', dpi=300)
  # plt.show()

if __name__ == '__main__':
  main()
