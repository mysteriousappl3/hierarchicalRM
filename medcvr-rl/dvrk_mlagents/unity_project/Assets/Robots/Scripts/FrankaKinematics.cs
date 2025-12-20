using System.Runtime.InteropServices;
using System.Collections.Generic;
using UnityEngine;
using static RobotController;
using UnityEditor;

public class FrankaKinemticsParameters
{
    public readonly int numLinks = 11;
    private readonly List<Dh> dhChain;
    public readonly SphericalWristToolParameters parameters;
    
    public readonly float link7_to_flange = 0.107f;
    public readonly float mount_offset = 0.0845f;
    public readonly float l1 = 0.333f;
    public readonly float l3 = 0.316f;
    public readonly float l4 = 0.0825f;
    public readonly float l5a = -0.0825f;
    public readonly float l5d = 0.384f;
    public readonly float l7 = 0.088f;
    public readonly float l8a = -0.0188f;
    public readonly float l8d;

    public FrankaKinemticsParameters(
        ToolAttachment toolAttachment, float scale = 1.0f)
    {
        link7_to_flange *= scale;
        mount_offset *= scale;
        
        parameters = SphericalWristToolParameters.Parameters[toolAttachment];
        parameters.lRcc *= scale;
        parameters.lTool *= scale;
        parameters.lPitch2Yaw *= scale;
        parameters.lYaw2Ctrlpnt *= scale;
        parameters.lTool2RcmOffset *= scale;
    
        l1 *= scale;
        l3 *= scale;
        l4 *= scale;
        l5a *= scale;
        l5d *= scale;
        l7 *= scale;
        l8a *= scale;

        l8d = parameters.lTool + mount_offset + link7_to_flange;

        dhChain = new List<Dh>
        {
            new Dh(0.0f,            0.0f,                  l1,                      0.0f,           Dh.JointType.REVOLUTE),
            new Dh(-Global.PI_2,    0.0f,                  0.0f,                    0.0f,           Dh.JointType.REVOLUTE),
            new Dh(Global.PI_2,     0.0f,                  l3,                      0.0f,           Dh.JointType.REVOLUTE),
            new Dh(Global.PI_2,     l4,                    0.0f,                    0.0f,           Dh.JointType.REVOLUTE),
            new Dh(-Global.PI_2,    l5a,                   l5d,                     0.0f,           Dh.JointType.REVOLUTE),
            new Dh(Global.PI_2,     0.0f,                  0.0f,                    0.0f,           Dh.JointType.REVOLUTE),
            new Dh(Global.PI_2,     l7,                    0.0f,                    0.0f,           Dh.JointType.REVOLUTE),
            new Dh(0.0f,            l8a,                   l8d,                     0.0f,           Dh.JointType.REVOLUTE),
            new Dh(-Global.PI_2,    0.0f,                  0.0f,                    -Global.PI_2,   Dh.JointType.REVOLUTE),
            new Dh(-Global.PI_2,    parameters.lPitch2Yaw, 0.0f,                    -Global.PI_2,   Dh.JointType.REVOLUTE),
            new Dh(-Global.PI_2,    0.0f,                  parameters.lYaw2Ctrlpnt, Global.PI_2,    Dh.JointType.REVOLUTE),
        };
    }

    public List<Dh> GetDhChain()
    {
        return dhChain;
    }
}

public class FrankaKinematics : Kinematics
{
#if UNITY_EDITOR_WIN || UNITY_STANDALONE_WIN
    [DllImport("FrankaPandaDLL",EntryPoint = "?franka_IK@@YAXPEAN0N0_N1@Z")]
#else // Try Linux
    [DllImport("libFrankaPandaDLL",EntryPoint = "_Z9franka_IKPdS_dS_bb")]
#endif
    public static extern void franka_IK([MarshalAs(UnmanagedType.LPArray, SizeParamIndex = 1)] 
                                            double[] q, double[] TF, double q7, 
                                            double[] q0, bool limit, bool flange);

    private readonly FrankaKinemticsParameters kinematicsData;
    private float scale;
    private float[] franka_old_q = new float[7] {0, 0, 0, 0, 0, 0, 0};
    private bool useRCM = true;
    private Vector3 rcmPosition;

    public FrankaKinematics(
        FrankaKinemticsParameters kinematicParameters,
        Vector3 rcm,
        float scale = 1.0f)
    {
        kinematicsData = kinematicParameters;
        dhChain = kinematicParameters.GetDhChain();
        numLinks = 11;
        this.scale = scale;
        // For reference, PSM RCM is (7.02, 0, 3.63)
        // Good rcm position for franka from testing is (6f, 0f, 5.63f)
        rcmPosition = rcm;
    }

    public void SetInitialJointValues(float[] q)
    {
        franka_old_q = q;
    }

    public void UpdateRCM(Vector3 rcm)
    {
        rcmPosition = rcm;
    }

    public void SetUseRCM(bool use)
    {
        useRCM = use;
    }

    public override float[] ComputeIK(Matrix4x4 T_EE_0)
    {
        // Note: T_x_y is the tranform x with respect to the y reference frame
        // base = 0, EE = end effector
      
        Matrix4x4 T_RCM_0 = Matrix4x4.TRS(rcmPosition, Quaternion.Euler(0f, 0f, -90f), Vector3.one);
        Matrix4x4 T_0_RCM = T_RCM_0.inverse;
        Matrix4x4 T_EE_RCM = T_0_RCM * T_EE_0;

        Matrix4x4 T_PinchJoint_EE = Matrix4x4.identity;
        T_PinchJoint_EE[2, 3] = -kinematicsData.parameters.lYaw2Ctrlpnt;

        Matrix4x4 T_PinchJoint_RCM = T_EE_RCM * T_PinchJoint_EE;
        Quaternion R_RCM_PinchJoint = T_PinchJoint_RCM.rotation;
        R_RCM_PinchJoint = Quaternion.Inverse(R_RCM_PinchJoint);

        Vector3 T_PinchJoint_RCM_p = GetUpper3OfColumn(T_PinchJoint_RCM, 3);

        Vector3 N_PalmJoint_PinchJoint = -1 * (R_RCM_PinchJoint * T_PinchJoint_RCM_p);
        N_PalmJoint_PinchJoint.x = 0.0f;
        N_PalmJoint_PinchJoint = N_PalmJoint_PinchJoint.normalized;

        Matrix4x4 T_PalmJoint_PinchJoint = Matrix4x4.identity;
        Vector3 T_PalmJoint_PinchJoint_p = N_PalmJoint_PinchJoint * kinematicsData.parameters.lPitch2Yaw;
        T_PalmJoint_PinchJoint[0, 3] = T_PalmJoint_PinchJoint_p.x;
        T_PalmJoint_PinchJoint[1, 3] = T_PalmJoint_PinchJoint_p.y;
        T_PalmJoint_PinchJoint[2, 3] = T_PalmJoint_PinchJoint_p.z;

        Matrix4x4 T_PalmJoint_RCM = T_EE_RCM * T_PinchJoint_EE * T_PalmJoint_PinchJoint;
        Vector3 T_PalmJoint_RCM_p = GetUpper3OfColumn(T_PalmJoint_RCM, 3);

        // Find Flange pose
        Matrix4x4 T_PalmJoint_0 = T_EE_0 * T_PinchJoint_EE * T_PalmJoint_PinchJoint;
        Vector3 T_PalmJoint_0_p = GetUpper3OfColumn(T_PalmJoint_0, 3);

        Vector3 flangePosition;
        Quaternion flangeRotation;
        float shaft_to_flange_length = kinematicsData.parameters.lTool + kinematicsData.mount_offset;
;
        if (useRCM)
        {
            Vector3 rcmDirection = rcmPosition - T_PalmJoint_0_p;
            rcmDirection = rcmDirection.normalized;
            flangeRotation = Quaternion.LookRotation(-rcmDirection, Vector3.up) * Quaternion.Euler(0.0f, 0.0f, 180.0f);
            flangePosition = T_PalmJoint_0_p + (shaft_to_flange_length * rcmDirection);
            flangePosition = flangePosition - kinematicsData.l8a * (flangeRotation * new Vector3(1.0f, 0.0f, 0.0f));
        }
        else
        {
            flangePosition = T_PalmJoint_0_p + new Vector3(0.0f, 0.0f, shaft_to_flange_length);
            flangeRotation = Quaternion.Euler(0.0f, 180.0f, 180.0f);
            flangePosition = flangePosition - kinematicsData.l8a * (flangeRotation * new Vector3(1.0f, 0.0f, 0.0f));
        }

        Matrix4x4 T_Flange = Matrix4x4.TRS(flangePosition / scale, flangeRotation, Vector3.one);

        double[] TF ={
            (double)T_Flange[0], (double)T_Flange[1], (double)T_Flange[2], (double)T_Flange[3],
            (double)T_Flange[4], (double)T_Flange[5], (double)T_Flange[6], (double)T_Flange[7],
            (double)T_Flange[8], (double)T_Flange[9], (double)T_Flange[10],(double)T_Flange[11],
            (double)T_Flange[12],(double)T_Flange[13],(double)T_Flange[14],(double)T_Flange[15]};
        
        double[] out_q = new double[7];
        
        double q7 = (double)(franka_old_q[6] + 45 * Mathf.Deg2Rad); // 45 deg offset
        double[] q0 = {
            (double)franka_old_q[0],
            (double)franka_old_q[1],
            (double)franka_old_q[2],
            (double)franka_old_q[3],
            (double)franka_old_q[4],
            (double)franka_old_q[5],
            (double)q7};

        franka_IK(out_q, TF, q7, q0, true, true);

        if (double.IsNaN(out_q[0]) ||
            double.IsNaN(out_q[1]) ||
            double.IsNaN(out_q[2]) ||
            double.IsNaN(out_q[3]) ||
            double.IsNaN(out_q[4]) ||
            double.IsNaN(out_q[5]) ||
            double.IsNaN(out_q[6]))
        {
            Debug.LogError("Invalid IK solution, using old joint values");
            return franka_old_q;
        }

        float[] q = new float[10];
        for(int i = 0 ; i < out_q.Length; i++)
        {
            q[i] = (float)out_q[i];
        }

        q[6] = q[6] - 45 * Mathf.Deg2Rad; // remove 45 deg offset

        Vector3 T_EE_R_UnitX = GetUpper3OfColumn(T_EE_RCM, 0);
        Vector3 cross_palmlink_x7_0 = Vector3.Cross(T_EE_R_UnitX, T_PinchJoint_RCM_p - T_PalmJoint_RCM_p);
        
        Matrix4x4 T_Link7_0 = ComputeFK(new float[] {
            q[0], q[1], q[2], q[3], q[4], q[5], q[6]}, 7);
        Matrix4x4 T_Link7_RCM = T_0_RCM * T_Link7_0;
        
        Vector3 T_RollJoint_R_UnitY = GetUpper3OfColumn(T_Link7_RCM, 1);
        Vector3 T_RollJoint_R_UnitZ = GetUpper3OfColumn(T_Link7_RCM, 2);
        float tool_roll = GetAngle(cross_palmlink_x7_0, T_RollJoint_R_UnitY, true, -1.0f * T_RollJoint_R_UnitZ);

        Matrix4x4 T_RollJoint_Link7 = GetDh(7).ToMat(tool_roll);
        Matrix4x4 T_RollJoint_RCM = T_Link7_RCM * T_RollJoint_Link7;

        Vector3 T_RollJoint_RCM_R_UnitY = GetUpper3OfColumn(T_RollJoint_RCM, 1);
        Vector3 T_RollJoint_RCM_R_UnitZ = GetUpper3OfColumn(T_RollJoint_RCM, 2);        
        float tool_pitch = GetAngle(
            T_PinchJoint_RCM_p - T_PalmJoint_RCM_p,
            T_RollJoint_RCM_R_UnitZ,
            true,
            -1.0f * T_RollJoint_RCM_R_UnitY);

        Matrix4x4 T_PitchJoint_RollJoint = GetDh(8).ToMat(tool_pitch);
        Matrix4x4 T_PitchJoint_RCM = T_RollJoint_RCM * T_PitchJoint_RollJoint;

        Vector3 T_PitchJoint_RCM_R_UnitX = GetUpper3OfColumn(T_PitchJoint_RCM, 0);
        Vector3 T_PitchJoint_RCM_R_UnitY = GetUpper3OfColumn(T_PitchJoint_RCM, 1);        
        Vector3 T_EE_RCM_R_UnitZ = GetUpper3OfColumn(T_EE_RCM, 2);

        float tool_yaw = GetAngle(
            T_EE_RCM_R_UnitZ,
            T_PitchJoint_RCM_R_UnitX,
            true,
            -1.0f * T_PitchJoint_RCM_R_UnitY);

        q[7] = tool_roll;
        q[8] = tool_pitch;
        q[9] = tool_yaw;

        for (int i = 0; i < 7; i++)
        {
            franka_old_q[i] = q[i];
        }

        return q;
    }
}
