""" PSM Kinematics for FK and IK calculations. 

Code borrowed from: https://github.com/kevinzakka/mjctrl/blob/main/diffik.py
Kinematics code borrowed from AMBF project:
https://github.com/surgical-robotics-ai/surgical_robotics_challenge 
"""

import numpy as np
import math
from medcvr_rl.kinematics.utils import *

class PSMKinematicData:
    def __init__(self):
        self.num_links = 7

        self.l_rcc = 0.4318
        self.l_tool = 0.4162
        self.l_pitch2yaw = 0.0091
        self.l_yaw2ctrlpnt = 0.0102
        self.l_tool2rcm_offset = self.l_rcc - self.l_tool

        # PSM DH Params
        self.kinematics = [
            DH(PI_2, 0, 0, 0, PI_2, JointType.REVOLUTE, Convention.MODIFIED),
            DH(-PI_2, 0, 0, 0, -PI_2, JointType.REVOLUTE, Convention.MODIFIED),
            DH(PI_2, 0, 0, 0, -self.l_rcc, JointType.PRISMATIC, Convention.MODIFIED),
            DH(0, 0, 0, self.l_tool, 0, JointType.REVOLUTE, Convention.MODIFIED),
            DH(-PI_2, 0, 0, 0, -PI_2, JointType.REVOLUTE, Convention.MODIFIED),
            DH(-PI_2, self.l_pitch2yaw, 0, 0, -PI_2, JointType.REVOLUTE, Convention.MODIFIED),
            DH(-PI_2, 0, 0, self.l_yaw2ctrlpnt, PI_2, JointType.REVOLUTE, Convention.MODIFIED)]

        self.lower_limits = [np.deg2rad(-91.96), np.deg2rad(-60), -0.0, np.deg2rad(-175), np.deg2rad(-90), np.deg2rad(-85)]
        self.upper_limits = [np.deg2rad(91.96), np.deg2rad(60), 0.240, np.deg2rad(175), np.deg2rad(90), np.deg2rad(85)]

    def get_link_params(self, link_num):
        if link_num < 0 or link_num > self.num_links:
            # Error
            print("ERROR, ONLY ", self.num_links, " JOINT DEFINED")
            return []
        else:
            return self.kinematics[link_num]


def compute_psm_fk(joint_pos, up_to_link, kinematics_data):
    if up_to_link > kinematics_data.num_links:
        raise "ERROR! COMPUTE FK UP_TO_LINK GREATER THAN DOF"
    j = [0, 0, 0, 0, 0, 0, 0]
    for i in range(len(joint_pos)):
        j[i] = joint_pos[i]

    T_N_0 = np.identity(4)

    for i in range(up_to_link):
        link_dh = kinematics_data.get_link_params(i)
        link_dh.theta = j[i]
        T_N_0 = T_N_0 * link_dh.get_trans()

    return T_N_0

def compute_psm_ik(T_7_0, kinematics_data):
    pkd = PSMKinematicData()
    T_Pinch_7 = np.identity(4)
    T_Pinch_7[0:3, 3] = [0.0, 0.0, -pkd.l_yaw2ctrlpnt]

    T_Pinch_0 = np.matmul(T_7_0, T_Pinch_7)

    R_0_Pinch = np.linalg.inv(T_Pinch_0[0:3, 0:3])
    P_Pinch_local = np.dot(R_0_Pinch, T_Pinch_0[0:3, 3])
    N_Palm_Pinch = -P_Pinch_local
    N_Palm_Pinch[0] = 0
    N_Palm_Pinch = N_Palm_Pinch / np.linalg.norm(N_Palm_Pinch)

    T_Palm_Pinch = np.identity(4)
    T_Palm_Pinch[0:3, 3] = N_Palm_Pinch * pkd.l_pitch2yaw

    T_Palm_0 = np.matmul(np.matmul(T_7_0, T_Pinch_7), T_Palm_Pinch)
    insertion_depth = np.linalg.norm(T_Palm_0[0:3, 3])

    xz_diagonal = math.sqrt(T_Palm_0[0, 3] ** 2 + T_Palm_0[2, 3] ** 2)

    j1 = math.atan2(T_Palm_0[0, 3], -T_Palm_0[2, 3])
    j2 = -math.atan2(T_Palm_0[1, 3], xz_diagonal)
    j3 = insertion_depth + pkd.l_tool2rcm_offset

    # Calculate j4
    cross_palmlink_x7_0 = np.cross(T_7_0[0:3, 0], (T_Pinch_0[0:3, 3] - T_Palm_0[0:3, 3]))
    T_3_0 = compute_psm_fk([j1, j2, j3], 3, kinematics_data)
    T_3_0_RY = np.squeeze(np.asarray(T_3_0.T[1, :3]))
    T_3_0_RZ = np.squeeze(np.asarray(T_3_0.T[2, :3]))
    j4 = get_angle(cross_palmlink_x7_0, T_3_0_RY, up_vector=-T_3_0_RZ)

    # Calculate j5
    link4_dh = kinematics_data.get_link_params(3)
    link4_dh.theta = j4
    T_4_3 = link4_dh.get_trans()
    T_4_0 = np.matmul(T_3_0, T_4_3)
    T_4_0_RY = np.squeeze(np.asarray(T_4_0.T[1, :3]))
    T_4_0_RZ = np.squeeze(np.asarray(T_4_0.T[2, :3]))

    j5 = get_angle(
        T_Pinch_0.T[3, :3] - T_Palm_0.T[3, :3],
        T_4_0_RZ,
        up_vector=-T_4_0_RY)

    # Calculate j6
    link5_dh = kinematics_data.get_link_params(4)
    link5_dh.theta = j5
    T_5_4 = link5_dh.get_trans()
    T_5_0 = np.matmul(T_4_0, T_5_4)
    T_7_0_RZ = np.squeeze(np.asarray(T_7_0.T[2, :3]))
    T_5_0_RX = np.squeeze(np.asarray(T_5_0.T[0, :3]))
    T_5_0_RY = np.squeeze(np.asarray(T_5_0.T[1, :3]))
    j6 = get_angle(T_7_0_RZ, T_5_0_RX, up_vector=-T_5_0_RY)

    return [j1, j2, j3, j4, j5, j6]
