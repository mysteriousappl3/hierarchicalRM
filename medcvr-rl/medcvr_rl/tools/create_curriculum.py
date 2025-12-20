#!/usr/bin/env python

"""create_curriculum.py: Create a curriculum from the provided data
  Arguments:
    Required:
    Optional:

  Usage:  create_curriculum.py [-h]
  Example usage: python create_curriculum.py
"""

import argparse
from medcvr_rl.curriculums.cutrope import CUTROPE_3D_CURRICULUM2 as CURRICULUM

MEASURE = 'reward'
BEHAVIOUR = 'CutRope'
SIGNAL_SMOOTHING = 'true'
MIN_LESSON_LENGTH = 300
THRESHOLD = 9.0 # Pushblock 2.5 # Cutrope 3.2 # CutRope 9.0
SAMPLER_TYPE = 'uniform'


def main(args):
  with open('curriculum.txt', 'w') as f:
    f.write('environment_parameters:\n')

    for var in CURRICULUM:
      f.write(f'  {var[0]}:\n')
      f.write('    curriculum:\n')
      for i, cur in enumerate(var[1]):
        f.write(f'      - name: Lesson{i}\n')
        if i < len(var[1]) - 1:
          f.write('        completion_criteria:\n')
          f.write(f'          measure: {MEASURE}\n')
          f.write(f'          behavior: {BEHAVIOUR}\n')
          f.write(f'          signal_smoothing: {SIGNAL_SMOOTHING}\n')
          f.write(f'          min_lesson_length: {MIN_LESSON_LENGTH}\n')
          f.write(f'          threshold: {THRESHOLD}\n')

        if isinstance(cur, tuple):
          f.write('        value:\n')
          f.write(f'          sampler_type: {SAMPLER_TYPE}\n')
          f.write('          sampler_parameters:\n')
          f.write(f'            min_value: {cur[0]}\n')
          f.write(f'            max_value: {cur[1]}\n')
        else:
          f.write(f'        value: {cur}\n')



if __name__ == '__main__':
  parser = argparse.ArgumentParser(description='Create a curriculum from the provided data')
  args = parser.parse_args()
  main(args)