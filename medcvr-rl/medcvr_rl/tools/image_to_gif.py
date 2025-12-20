#!/usr/bin/env python

"""image_to_gif.py: Convert images in a directory to GIF
  Arguments:
    Required:
    -d, --data = location of data

    Optional:

  Usage:  visualize_bbox_coco.py [-h] -d DATA
  Example usage: python src/visualize/image_to_gif.py -d data/processed/incision_1/
"""

import argparse
import glob
from os.path import isfile, isdir

import cv2
import numpy as np
from PIL import Image


# TODO(Mustafa): Make this more flexible for filtering specific file names (e.g. images with a certain prefix etc.)


def main(args):
  if not isdir(args.data):
    print('Data folder does not exist')
    return

  # filepaths
  fp_in = f'{args.data}/cropped_*.jpg'
  num_files = len(glob.glob(fp_in))

  if args.out == '':
    fp_out = f'{args.data}{args.filename}.gif'
  else:
    fp_out = f'{args.out}{args.filename}.gif'

  # https://pillow.readthedocs.io/en/stable/handbook/image-file-formats.html#gif
  img, *imgs = [Image.open(f'{args.data}/cropped_{f}.jpg') for f in range(num_files)]
  img.save(fp=fp_out, format='GIF', append_images=imgs, save_all=True, duration=args.duration, loop=0)


if __name__ == '__main__':
  parser = argparse.ArgumentParser(description='Convert images into a gif')
  parser.add_argument('-d', '--data', type=str, required=True, help='location of images to convert to gif')
  parser.add_argument('-o', '--out', type=str, default='', help='directory to store output gif (Default = data directory).')
  parser.add_argument('-l', '--duration', type=int, default=33, help='length of the GIF in milliseconds')
  parser.add_argument('-f', '--filename', type=str, help='name of file to combine into gif')
  args = parser.parse_args()
  main(args)