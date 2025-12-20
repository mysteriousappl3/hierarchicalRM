#!/usr/bin/env python

"""depth_to_pointcloud.py: Convert RGBD image to point cloud
  Arguments:
    Required:
    -f, --file = location of RGBD image file

    Optional:

  Usage:  visualize_bbox_coco.py [-h] -f FILE
  Example usage: python depth_to_pointcloud -f my_image.png
"""

import os
import argparse
import numpy as np
import math
from PIL import Image
import open3d as o3d

def to_rad(th):
  return th*math.pi / 180

def depth_to_pointcloud(args):
  if not os.path.exists:
    print("Path is not valid!")
    return

  # Open Image
  img = Image.open(args.file)
  depth = np.asarray(img)
  # depth is the last channel
  color = o3d.geometry.Image(depth[:, :, :3].astype(np.uint8))
  depth = o3d.geometry.Image(depth[:, :, 3].astype(np.uint8))

  width, height = 64, 64
  fov = 60

  # Convert fov to focal length
  focal_length = 0.5 * width / math.tan(to_rad(fov/2))
  # camera intrinsics
  fx, fy, cx, cy = (focal_length, focal_length, width/2, height/2)

  rgbd = o3d.geometry.RGBDImage.create_from_color_and_depth(
    color,
    depth,
    depth_scale=1,
    depth_trunc=100,
    convert_rgb_to_intensity = False)
  pinhole_camera_intrinsic = o3d.camera.PinholeCameraIntrinsic(width, height, fx, fy, cx, cy)
  pcd = o3d.geometry.PointCloud.create_from_rgbd_image(rgbd, pinhole_camera_intrinsic)

  # flip the orientation, so it looks upright, not upside-down
  pcd.transform([[1,0,0,0],[0,-1,0,0],[0,0,-1,0],[0,0,0,1]])

  o3d.visualization.draw_geometries([pcd])    # visualize the point cloud

if __name__ == "__main__":
  parser = argparse.ArgumentParser(description='Convert image to point cloud')
  parser.add_argument('-f', '--file', type=str, required=True, help='path to file')
  args = parser.parse_args()
  depth_to_pointcloud(args)