#!/usr/bin/env python

"""image_to_vid.py: Convert images in a directory to mp4 video
  Arguments:
    Required:
    -d, --data = location of data

    Optional:
    -o, --out = output location

  Usage:  visualize_bbox_coco.py [-h] -d DATA -o OUTPUT
  Example usage: python src/visualize/image_to_vid.py -d data/processed/incision_1/
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

  if args.out == '':
    fp_out = f'{args.data}{args.filename}.avi'
  else:
    fp_out = f'{args.out}{args.filename}.avi'

  num_files = len(glob.glob(fp_in))

  img_array = []

  for i in range(num_files - 1):
    path = f'{args.data}/cropped_{i * args.skip}.jpg'
    img = cv2.imread(path)
    h, w, l = img.shape
    size = (w, h)
    img_array.append(img)

  out = cv2.VideoWriter(fp_out, cv2.VideoWriter_fourcc(*'DIVX'), 8, size)

  for i in range(len(img_array)):
    out.write(img_array[i])
  out.release()


if __name__ == '__main__':
  parser = argparse.ArgumentParser(description='Convert images into a gif')
  parser.add_argument('-d', '--data', type=str, required=True, help='location of images to convert to gif')
  parser.add_argument('-o', '--out', type=str, default='', help='directory to store output gif (Default = data directory).')
  parser.add_argument('-s', '--skip', type=int, default=0, help='Frame skip')
  parser.add_argument('-l', '--duration', type=int, default=33, help='length of the GIF in milliseconds')
  parser.add_argument('-f', '--filename', type=str, help='name of file to combine into gif')
  args = parser.parse_args()
  main(args)