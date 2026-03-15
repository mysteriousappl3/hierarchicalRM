using System.Collections.Generic;
using UnityEngine;
using static RobotController;

// For the psm kinematics explanation, follow
// dvrk_planning/src/dvrk_planning/kinematics/psm.py

public struct SphericalWristToolParameters
{
    public float lRcc;
    public float lTool;
    public float lPitch2Yaw; // Fixed length from the palm joint to the pinch joint
    public float lYaw2Ctrlpnt; // Fixed length from the pinch joint to the pinch tip
    public float lTool2RcmOffset; // Delta between tool tip and the Remote Center of Motion

    public SphericalWristToolParameters(
        float lRcc,
        float lTool,
        float lPitch2Yaw,
        float lYaw2Ctrlpnt)
    {
        this.lRcc = lRcc;
        this.lTool = lTool;
        this.lPitch2Yaw = lPitch2Yaw;
        this.lYaw2Ctrlpnt = lYaw2Ctrlpnt;
        lTool2RcmOffset = this.lRcc - this.lTool;
    }

    public static Dictionary<
       ToolAttachment,
        SphericalWristToolParameters> Parameters = new Dictionary<
            ToolAttachment, SphericalWristToolParameters>
    {
        {ToolAttachment.LargeNeedleDriver,
            new SphericalWristToolParameters(0.4318f, 0.4162f, 0.0091f, 0.0102f)},
        {ToolAttachment.CaudiereForceps,
            new SphericalWristToolParameters(0.4318f, 0.4162f, 0.0091f, 0.01977f)},
        {ToolAttachment.RoundTipScissor,
            new SphericalWristToolParameters(0.4318f, 0.4162f, 0.0091f, 0.01041f)}
    };
}

public class PSMKinematicParameters
{
    private readonly List<Dh> dhChain;
    public readonly SphericalWristToolParameters parameters;

    public PSMKinematicParameters(
        ToolAttachment toolAttachment, float scale = 1.0f)
    {
        parameters = SphericalWristToolParameters.Parameters[toolAttachment];
        parameters.lRcc *= scale;
        parameters.lTool *= scale;
        parameters.lPitch2Yaw *= scale;
        parameters.lYaw2Ctrlpnt *= scale;
        parameters.lTool2RcmOffset *= scale;

        dhChain = new List<Dh> {
            new Dh( Global.PI_2, 0.0f,                  0.0f,                   Global.PI_2,      Dh.JointType.REVOLUTE),
            new Dh(-Global.PI_2, 0.0f,                  0.0f,                   -Global.PI_2,     Dh.JointType.REVOLUTE),
            new Dh( Global.PI_2, 0.0f,                  0.0f,                   -parameters.lRcc, Dh.JointType.PRISMATIC),
            new Dh(        0.0f, 0.0f,                  parameters.lTool,       0.0f,             Dh.JointType.REVOLUTE),
            new Dh(-Global.PI_2, 0.0f,                  0.0f,                   -Global.PI_2,     Dh.JointType.REVOLUTE),
            new Dh(-Global.PI_2, parameters.lPitch2Yaw, 0.0f,                   -Global.PI_2,     Dh.JointType.REVOLUTE),
            new Dh(-Global.PI_2, 0.0f,                  parameters.lYaw2Ctrlpnt, Global.PI_2,     Dh.JointType.REVOLUTE)};
    }

    public List<Dh> GetDHChain()
    {
        return dhChain;
    }
}

public class PSMKinematics : Kinematics
{
    private readonly PSMKinematicParameters kinematicsData;

    public PSMKinematics(PSMKinematicParameters kinematicsParameters)
    {
        kinematicsData = kinematicsParameters;
        dhChain = kinematicsData.GetDHChain();
        numLinks = 7;
    }

    // Obtained from:
    // https://github.com/collaborative-robotics/surgical_robotics_challenge/tree/master/scripts/surgical_robotics_challenge/kinematics
    public override float[] ComputeIK(Matrix4x4 T70)
    {
        Matrix4x4 T_PinchJoint_7 = Matrix4x4.identity;
        T_PinchJoint_7[2, 3] = -kinematicsData.parameters.lYaw2Ctrlpnt;
        Matrix4x4 T_PinchJoint_0 = T70 * T_PinchJoint_7;

        Quaternion R_0_PinchJoint = T_PinchJoint_0.rotation;
        R_0_PinchJoint = Quaternion.Inverse(R_0_PinchJoint);

        Vector3 T_PinchJoint_0_p = GetUpper3OfColumn(T_PinchJoint_0, 3);

        Vector3 N_PalmJoint_PinchJoint = -1 * (R_0_PinchJoint * T_PinchJoint_0_p);
        N_PalmJoint_PinchJoint.x = 0.0f;
        N_PalmJoint_PinchJoint = N_PalmJoint_PinchJoint.normalized;

        Matrix4x4 T_PalmJoint_PinchJoint = Matrix4x4.identity;
        Vector3 T_PalmJoint_PinchJoint_p = N_PalmJoint_PinchJoint * kinematicsData.parameters.lPitch2Yaw;
        T_PalmJoint_PinchJoint[0, 3] = T_PalmJoint_PinchJoint_p.x;
        T_PalmJoint_PinchJoint[1, 3] = T_PalmJoint_PinchJoint_p.y;
        T_PalmJoint_PinchJoint[2, 3] = T_PalmJoint_PinchJoint_p.z;

        Matrix4x4 T_PalmJoint_0 = (T70 * T_PinchJoint_7) * T_PalmJoint_PinchJoint;

        Vector3 T_PalmJoint_0_p = GetUpper3OfColumn(T_PalmJoint_0, 3);
        float insertionDepth = T_PalmJoint_0_p.magnitude;

        // Angle calculations
        float xz_diag = Mathf.Sqrt(Mathf.Pow(T_PalmJoint_0_p.x, 2.0f) + Mathf.Pow(T_PalmJoint_0_p.z, 2.0f));

        float j1 = Mathf.Atan2(T_PalmJoint_0_p.x, (-1.0f * T_PalmJoint_0_p.z));
        float j2 = -1 * Mathf.Atan2(T_PalmJoint_0_p.y, xz_diag);
        float j3 = insertionDepth + kinematicsData.parameters.lTool2RcmOffset;

        Vector3 T_7_0_R_UnitX = GetUpper3OfColumn(T70, 0);

        // Calculate j4
        Vector3 cross_palmlink_x7_0 = Vector3.Cross(T_7_0_R_UnitX, (T_PinchJoint_0_p - T_PalmJoint_0_p));
        Matrix4x4 T_3_0 = ComputeFK(new float[] { j1, j2, j3 }, 3);
        Vector3 T_3_0_R_UnitY = GetUpper3OfColumn(T_3_0, 1);
        Vector3 T_3_0_R_UnitZ = GetUpper3OfColumn(T_3_0, 2);

        float j4 = GetAngle(cross_palmlink_x7_0, T_3_0_R_UnitY, true, -1.0f * T_3_0_R_UnitZ);

        Matrix4x4 T_4_3 = GetDh(3).ToMat(j4);
        Matrix4x4 T_4_0 = T_3_0 * T_4_3;
        Vector3 T_4_0_R_UnitY = GetUpper3OfColumn(T_4_0, 1);
        Vector3 T_4_0_R_UnitZ = GetUpper3OfColumn(T_4_0, 2);
        float j5 = GetAngle(T_PinchJoint_0_p - T_PalmJoint_0_p, T_4_0_R_UnitZ, true, -1.0f * T_4_0_R_UnitY);

        Matrix4x4 T_5_4 = GetDh(4).ToMat(j5);
        Matrix4x4 T_5_0 = T_4_0 * T_5_4;
        Vector3 T_5_0_R_UnitX = GetUpper3OfColumn(T_5_0, 0);
        Vector3 T_5_0_R_UnitY = GetUpper3OfColumn(T_5_0, 1);
        Vector3 T_7_0_R_UnitZ = GetUpper3OfColumn(T70, 2);

        float j6 = GetAngle(T_7_0_R_UnitZ, T_5_0_R_UnitX, true, -1.0f * T_5_0_R_UnitY);

        return new float[] { j1, j2, j3, j4, j5, j6 };
    }
}
