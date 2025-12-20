'''
Pure JAX implementation of PSM kinematics for accelerated computation on GPU
'''

import numpy as np
import jax
import jax.numpy as jp
from brax import math

PI = np.pi
PI_2 = np.pi/2

def mat_from_dh_revolute(alpha, a, theta, d, offset):
	ca = jp.cos(alpha)
	sa = jp.sin(alpha)
	th = 0.0
	th = theta + offset
	ct = jp.cos(th)
	st = jp.sin(th)
	mat = jp.asarray([
			[ct, -st, 0, a],
			[st * ca, ct * ca, -sa, -d * sa],
			[st * sa, ct * sa, ca, d * ca],
			[0, 0, 0, 1]])
	return mat

def mat_from_dh_prismatic(alpha, a, theta, d, offset):
	ca = jp.cos(alpha)
	sa = jp.sin(alpha)
	th = 0.0
	d = d + offset + theta
	ct = jp.cos(th)
	st = jp.sin(th)
	mat = jp.asarray([
		[ct, -st, 0, a],
		[st * ca, ct * ca, -sa, -d * sa],
		[st * sa, ct * sa, ca, d * ca],
		[0, 0, 0, 1]])
	return mat

def compute_psm_fk_up_to_3(joint_pos, l_rcc=0.4318):
	T_3_0 = jp.identity(4)
	T_1_0 = mat_from_dh_revolute(PI_2, 0, joint_pos[0], 0, PI_2)
	T_2_1 = mat_from_dh_revolute(-PI_2, 0, joint_pos[1], 0, -PI_2)
	T_3_2 = mat_from_dh_prismatic(PI_2, 0, joint_pos[2], 0, -l_rcc)

	T_3_0 = jp.matmul(T_3_0, T_1_0)
	T_3_0 = jp.matmul(T_3_0, T_2_1)
	T_3_0 = jp.matmul(T_3_0, T_3_2)

	return T_3_0

def compute_psm_fk(joint_pos, l_rcc=0.4318, l_tool=0.4162, l_yaw2ctrlpnt=0.0102, l_pitch2yaw=0.0091):
	T_7_0 = compute_psm_fk_up_to_3(joint_pos[:3])
	T_4_3 = mat_from_dh_revolute(0, 0, joint_pos[3], l_tool, 0)
	T_5_4 = mat_from_dh_revolute(-PI_2, 0, joint_pos[4], 0, -PI_2)
	T_6_5 = mat_from_dh_revolute(-PI_2, l_pitch2yaw, joint_pos[5], 0, -PI_2)
	T_7_6 = mat_from_dh_revolute(-PI_2, 0, 0, l_yaw2ctrlpnt, PI_2)

	T_7_0 = jp.matmul(T_7_0, T_4_3)
	T_7_0 = jp.matmul(T_7_0, T_5_4)
	T_7_0 = jp.matmul(T_7_0, T_6_5)
	T_7_0 = jp.matmul(T_7_0, T_7_6)

	return T_7_0

def compute_psm_ik(T_7_0, l_rcc=0.4318, l_tool=0.4162, l_yaw2ctrlpnt=0.0102, l_pitch2yaw=0.0091) -> jax.Array:
	l_tool2rcm_offset = l_rcc - l_tool
	T_Pinch_7 = jp.identity(4)
	T_Pinch_7 = T_Pinch_7.at[2, 3].set(-l_yaw2ctrlpnt)

	T_Pinch_0 = jp.matmul(T_7_0, T_Pinch_7)

	R_0_Pinch = jp.linalg.inv(T_Pinch_0[0:3, 0:3])
	P_Pinch_local = jp.dot(R_0_Pinch, T_Pinch_0[0:3, 3])
	N_Palm_Pinch = -P_Pinch_local
	N_Palm_Pinch = N_Palm_Pinch.at[0].set(0)
	N_Palm_Pinch = N_Palm_Pinch / jp.linalg.norm(N_Palm_Pinch)

	T_Palm_Pinch = jp.identity(4)
	T_Palm_Pinch = T_Palm_Pinch.at[0:3, 3].set(N_Palm_Pinch * l_pitch2yaw)

	T_Palm_0 = jp.matmul(jp.matmul(T_7_0, T_Pinch_7), T_Palm_Pinch)
	insertion_depth = jp.linalg.norm(T_Palm_0[0:3, 3])

	xz_diagonal = jp.sqrt(T_Palm_0[0, 3] ** 2 + T_Palm_0[2, 3] ** 2)

	j1 = jp.arctan2(T_Palm_0[0, 3], -T_Palm_0[2, 3])
	j2 = -jp.arctan2(T_Palm_0[1, 3], xz_diagonal)
	j3 = insertion_depth + l_tool2rcm_offset

	# Calculate j4
	cross_palmlink_x7_0 = jp.cross(T_7_0[0:3, 0], (T_Pinch_0[0:3, 3] - T_Palm_0[0:3, 3]))
	T_3_0 = compute_psm_fk_up_to_3([j1, j2, j3])
	T_3_0_RY = jp.squeeze(jp.asarray(T_3_0.T[1, :3]))
	T_3_0_RZ = jp.squeeze(jp.asarray(T_3_0.T[2, :3]))
	j4 = math.signed_angle(-T_3_0_RZ, cross_palmlink_x7_0, T_3_0_RY)

	# Calculate j5
	T_4_3 = mat_from_dh_revolute(0, 0, j4, l_tool, 0)
	T_4_0 = jp.matmul(T_3_0, T_4_3)
	T_4_0_RY = jp.squeeze(jp.asarray(T_4_0.T[1, :3]))
	T_4_0_RZ = jp.squeeze(jp.asarray(T_4_0.T[2, :3]))
	j5 = math.signed_angle(-T_4_0_RY, T_Pinch_0.T[3, :3] - T_Palm_0.T[3, :3], T_4_0_RZ)

	# Calculate j6
	T_5_4 = mat_from_dh_revolute(-PI_2, 0, j5, 0, -PI_2)
	T_5_0 = jp.matmul(T_4_0, T_5_4)
	T_7_0_RZ = jp.squeeze(jp.asarray(T_7_0.T[2, :3]))
	T_5_0_RX = jp.squeeze(jp.asarray(T_5_0.T[0, :3]))
	T_5_0_RY = jp.squeeze(jp.asarray(T_5_0.T[1, :3]))
	j6 = math.signed_angle(-T_5_0_RY, T_7_0_RZ, T_5_0_RX)

	return jp.asarray([j1, j2, j3, j4, j5, j6])