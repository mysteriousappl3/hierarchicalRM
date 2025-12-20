""" Generic Kinematics helper classes/functions 

Code borrowed from AMBF project:
https://github.com/surgical-robotics-ai/surgical_robotics_challenge
"""

import numpy as np
from enum import Enum
import math

PI = np.pi
PI_2 = np.pi/2

class JointType(Enum):
    REVOLUTE = 0
    PRISMATIC = 1

class Convention(Enum):
    STANDARD = 0
    MODIFIED = 1

class DH:
    def __init__(self, alpha, a, theta, d, offset, joint_type, convention):
        self.alpha = alpha
        self.a = a
        self.theta = theta
        self.d = d
        self.offset = offset
        self.joint_type = joint_type
        self.convention = convention

    def mat_from_dh(self, alpha, a, theta, d, offset, joint_type, convention):
        ca = np.cos(alpha)
        sa = np.sin(alpha)
        th = 0.0
        if joint_type == JointType.REVOLUTE:
            th = theta + offset
        elif joint_type == JointType.PRISMATIC:
            d = d + offset + theta
        else:
            assert joint_type == JointType.REVOLUTE and joint_type == JointType.PRISMATIC
            return

        ct = np.cos(th)
        st = np.sin(th)

        if convention == Convention.STANDARD:
            mat = np.mat([
                [ct, -st * ca,  st * sa,  a * ct],
                [st,  ct * ca, -ct * sa,  a * st],
                [0,        sa,       ca,       d],
                [0,         0,        0,       1]
            ])
        elif convention == Convention.MODIFIED:
            mat = np.mat([
                [ct, -st, 0, a],
                [st * ca, ct * ca, -sa, -d * sa],
                [st * sa, ct * sa, ca, d * ca],
                [0, 0, 0, 1]
            ])
        else:
            raise 'ERROR, DH CONVENTION NOT UNDERSTOOD'

        return mat

    def get_trans(self):
        return self.mat_from_dh(self.alpha, self.a, self.theta, self.d, self.offset, self.joint_type, self.convention)


def enforce_limits(j_raw, lower_lims, upper_lims):
    num_joints = len(j_raw)
    j_limited = [0.0]*num_joints

    for idx in range(num_joints):
        min_lim = lower_lims[idx]
        max_lim = upper_lims[idx]
        j_limited[idx] = max(min_lim, min(j_raw[idx], max_lim))

    return j_limited


def get_angle(vec_a, vec_b, up_vector=None):
    vec_a = vec_a / np.linalg.norm(vec_a)
    vec_b = vec_b / np.linalg.norm(vec_b)
    cross_ab = np.cross(vec_a, vec_b)
    vdot = np.dot(vec_a, vec_b)

    # Check if the vectors are in the same direction
    if 1.0 - vdot < 0.000001:
        angle = 0.0
        # Or in the opposite direction
    elif 1.0 + vdot < 0.000001:
        angle = np.pi
    else:
        angle = np.arccos(vdot)

    if up_vector is not None:
        same_dir = np.sign(np.dot(cross_ab, up_vector))
        if same_dir < 0.0:
            angle = -angle

    return angle


def round_mat(mat, rows, cols, precision=4):
    for i in range(0, rows):
        for j in range(0, cols):
            mat[i, j] = round(mat[i, j], precision)
    return mat


def round_vec(vec, precision=4):
    for i in range(3):
        vec[i] = round(vec[i], precision)
    return vec


def quaternion_inverse(quaternion):
    q = np.array(quaternion, dtype=np.float64, copy=True)
    np.negative(q[1:], q[1:])
    return q / np.dot(q, q)