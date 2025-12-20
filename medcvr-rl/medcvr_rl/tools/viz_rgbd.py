import os
import glob
import numpy as np
from PIL import Image
import open3d as o3d

import numpy as np
import OpenEXR as exr
import Imath

def readEXR(filename):
  """Read color + depth data from EXR image file.
  
  Parameters
  ----------
  filename : str
    File path.
    
  Returns
  -------
  img : RGB or RGBA image in float32 format. Each color channel
      lies within the interval [0, 1].
      Color conversion from linear RGB to standard RGB is performed
      internally. See https://en.wikipedia.org/wiki/SRGB#The_forward_transformation_(CIE_XYZ_to_sRGB)
      for more information.
      
  Z : Depth buffer in float32 format or None if the EXR file has no Z channel.
  """
  
  exrfile = exr.InputFile(filename)
  header = exrfile.header()
  
  dw = header['dataWindow']
  isize = (dw.max.y - dw.min.y + 1, dw.max.x - dw.min.x + 1)
  
  channelData = dict()
  
  # convert all channels in the image to numpy arrays
  for c in header['channels']:
    C = exrfile.channel(c, Imath.PixelType(Imath.PixelType.FLOAT))
    C = np.fromstring(C, dtype=np.float32)
    C = np.reshape(C, isize)
    
    channelData[c] = C
  
  colorChannels = ['R', 'G', 'B', 'A'] if 'A' in header['channels'] else ['R', 'G', 'B']
  img = np.concatenate([channelData[c][...,np.newaxis] for c in colorChannels], axis=2)
  
  # linear to standard RGB
  img[..., :3] = np.where(img[..., :3] <= 0.0031308,
              12.92 * img[..., :3],
              1.055 * np.power(img[..., :3], 1 / 2.4) - 0.055)
  
  # sanitize image to be in range [0, 1]
  img = np.where(img < 0.0, 0.0, np.where(img > 1.0, 1, img))
  
  Z = None if 'Z' not in header['channels'] else channelData['Z']
  
  return img, Z

def main():
  if not os.path.exists:
    print("Path is not valid!")
    return

  # image_paths = glob.glob('../dvrk_mlagents/unity_project/data/43-16-05-01-2023/episode_0/images/*png')
  #image_paths = glob.glob('C:/test/*.png')
  rgb, depth = readEXR('C:/test/test.exr')
  #image = Image.open('C:/test/hdr_test.png')
  #np_image = np.asarray(image)

  #rgb = np_image[:, :, 0:3]
  #depth = np_image[:, :, 1]

  vertices = []
  for x in range(depth.shape[0]):
    for y in range(depth.shape[1]):
      vertices.append((float(x), float(y), depth[x][y]))
  pcd = o3d.geometry.PointCloud()
  point_cloud = np.asarray(np.array(vertices))
  pcd.points = o3d.utility.Vector3dVector(point_cloud)
  pcd.estimate_normals()
  pcd = pcd.normalize_normals()
  o3d.visualization.draw_geometries([pcd])


if __name__ == "__main__":
  main()