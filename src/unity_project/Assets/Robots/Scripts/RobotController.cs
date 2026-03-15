using System.Collections.Generic;
using UnityEngine;
using NaughtyAttributes;

public struct RobotSignal
{
    public Vector3 PositionSignal;
    public Vector3 RotationSignal;
    public float JawSignal;
}

[RequireComponent(typeof(JointController))]
[DefaultExecutionOrder(-100)]
public class RobotController : MonoBehaviour
{
    public enum ControllerType {Joint, Cartesian, Primitive};
    [SerializeField]
    public ControllerType Controller = ControllerType.Cartesian;

    public enum Robot {PSM};
    [SerializeField]
    public Robot RobotType = Robot.PSM;

    public enum ToolAttachment { LargeNeedleDriver, RoundTipScissor, CaudiereForceps};
    [SerializeField]
    public ToolAttachment Tool = ToolAttachment.LargeNeedleDriver;

    public GameObject BaseLink;
    
    [Header("Cartesian Parameters")]
    [ShowIf("Controller", ControllerType.Cartesian)]
    public Vector2 XPositionLimit = new Vector2(-3f, 3f);
    [ShowIf("Controller", ControllerType.Cartesian)]
    public Vector2 YPositionLimit = new Vector2(-3f, 3f);
    [ShowIf("Controller", ControllerType.Cartesian)]
    public Vector2 ZPositionLimit = new Vector2(-3f, 3f);
    [ShowIf("Controller", ControllerType.Cartesian)]
    public Vector2 XRotationLimit = new Vector2(-60f, 85f);
    [ShowIf("Controller", ControllerType.Cartesian)]
    public Vector2 YRotationLimit = new Vector2(-180, 180f);
    [ShowIf("Controller", ControllerType.Cartesian)]
    public Vector2 ZRotationLimit = new Vector2(-85f, 85f);
    [ShowIf("Controller", ControllerType.Cartesian)]
    public float JawMaxInterpolationSpeedRad = 0.3f;
    [ShowIf("Controller", ControllerType.Cartesian)]
    public float MinJawAngleRadians = 0.0f;
    [ShowIf("Controller", ControllerType.Cartesian)]
    public float MaxJawAngleRadians = 0.5f;
    
    [Header("Primitive Parameters")]
    [ShowIf("Controller", ControllerType.Primitive)]
    public List<MotionPrimitiveType> PrimitiveLibrary = new List<MotionPrimitiveType>();

    private bool initialized = false;
    private JointController jointController;
    private Kinematics kinematics;
    private Pose startTipPose = Pose.identity;
    private Pose currentTipPose = Pose.identity;
    private Pose currentTipPosewrtWorld = Pose.identity;
    private Pose invBaseLinkPose = Pose.identity;
    private Vector3 referenceRotation = new Vector3(0, 0, 0);
    private BasePrimitive currentPrimitive = null;
    private bool jawEnabled = false;
    private float startJawAngle = 0f;
    private float currentJawAngle = 0f;

    enum AxisConversionMode {Urdf, Mujoco}
    private AxisConversionMode axisConversion = AxisConversionMode.Urdf;

    public void Awake()
    {
        Initialize();
    }

    public void Initialize()
    {
        if (RobotType == Robot.PSM)
        {
            kinematics = new PSMKinematics(
                new PSMKinematicParameters(Tool, this.transform.localScale.x));
        }
        else
        {
            Debug.LogError("Robot type not supported: " + RobotType.ToString());
        }

        if (initialized) return;
        jointController = GetComponent<JointController>();
        if (jointController is UrdfJointController) axisConversion = AxisConversionMode.Urdf;
        jointController.Initialize();
        InitializeIKController();
        initialized = true;
    }

    private void InitializeIKController()
    {
        int nl = kinematics.GetNumberOfLinks();
        float[] startJointPositions = new float[nl - 1];
        string[] activeJointNames = GetActiveJointNames();
        for (int i = 0; i < startJointPositions.Length; i++)
        {
            startJointPositions[i] = jointController.GetStartJointPosition(
                activeJointNames[i]);
        }

        Matrix4x4 poseMat = kinematics.ComputeFK(
            startJointPositions, kinematics.GetNumberOfLinks());
        startTipPose = ControllerUtils.ConvertMatToPose(poseMat);
        startTipPose = ConvertRobotPose(startTipPose);

        currentTipPose = startTipPose;
        currentTipPosewrtWorld = ControllerUtils.TransformPose(
            currentTipPose,
            new Pose(BaseLink.transform.position, BaseLink.transform.rotation));
        
        invBaseLinkPose.rotation = Quaternion.Inverse(BaseLink.transform.rotation);
        invBaseLinkPose.position = -(invBaseLinkPose.rotation * BaseLink.transform.position);
        referenceRotation = currentTipPosewrtWorld.rotation.eulerAngles;

        if (jointController.jawDetected)
        {
            jawEnabled = true;
            startJawAngle = 0f;
            currentJawAngle = 0f;
        }
    }

    public void ResetTip()
    {
        jointController.ResetToStartJointPositions();

        currentTipPose = startTipPose;
        currentTipPosewrtWorld = ControllerUtils.TransformPose(
            currentTipPose,
            new Pose(BaseLink.transform.position, BaseLink.transform.rotation));
        currentJawAngle = startJawAngle;
        referenceRotation = currentTipPosewrtWorld.rotation.eulerAngles;
    }

    public void ResetTip(
        Vector3 tipPositionwrtWorld, Quaternion tipRotationwrtWorld)
    {
        Pose tipPosewrtBase = ControllerUtils.TransformWorldToLocal(
            new Pose(tipPositionwrtWorld, tipRotationwrtWorld),
            new Pose(BaseLink.transform.position, BaseLink.transform.rotation));
        
        Pose convertedPose = ConvertUnityPose(tipPosewrtBase);

        float[] jp = kinematics.ComputeIK(
            convertedPose.position,
            convertedPose.rotation);

        int nj = kinematics.GetNumberOfLinks();
        if (jawEnabled) nj++;

        float[] jointPositions = new float[nj];
        for (int i = 0; i < jp.Length; i++)
        {
            jointPositions[i] = jp[i];
        }

        if (jawEnabled) jointPositions[jointPositions.Length - 1] = startJawAngle;
        jointController.ResetToJointPositions(GetActiveJointNames(), jointPositions);

        currentTipPose = tipPosewrtBase;
        currentTipPosewrtWorld = new Pose(tipPositionwrtWorld, tipRotationwrtWorld);
        currentJawAngle = startJawAngle;
        referenceRotation = currentTipPosewrtWorld.rotation.eulerAngles;
    }

    public (Vector3, Vector3) CalculateMoveTipPosition(Vector3 positionDelta)
    {
        Vector3 newPositionwrtWorld = positionDelta + currentTipPosewrtWorld.position;

        if (this.transform.parent != null)
        {
            Vector3 parentScenePosition = this.transform.parent.position;
            newPositionwrtWorld.x = Mathf.Clamp(
                newPositionwrtWorld.x,
                parentScenePosition.x + XPositionLimit[0],
                parentScenePosition.x + XPositionLimit[1]);
            newPositionwrtWorld.y = Mathf.Clamp(
                newPositionwrtWorld.y,
                parentScenePosition.y + YPositionLimit[0],
                parentScenePosition.y + YPositionLimit[1]);
            newPositionwrtWorld.z = Mathf.Clamp(
                newPositionwrtWorld.z,
                parentScenePosition.z + ZPositionLimit[0],
                parentScenePosition.z + ZPositionLimit[1]);
        }

        Vector3 newPositionwrtBase = invBaseLinkPose.rotation * 
            (newPositionwrtWorld - BaseLink.transform.position);
        
        return (newPositionwrtBase, newPositionwrtWorld);
    }

    public (Quaternion, Quaternion) CalculateMoveTipRotation(Vector3 rotationDelta)
    {
        Vector3 newRotation = referenceRotation + rotationDelta;

        if (newRotation.x < XRotationLimit[0] || newRotation.x > XRotationLimit[1])
        {
            rotationDelta.x = 0;
        }
        if (newRotation.y < YRotationLimit[0] || newRotation.y > YRotationLimit[1])
        {
            rotationDelta.y = 0;
        }
        if (newRotation.z < 180 + ZRotationLimit[0] || newRotation.z > 180 + ZRotationLimit[1])
        {
            rotationDelta.z = 0;
        }
        referenceRotation += rotationDelta;

        Quaternion delta = Quaternion.Euler(rotationDelta);
        Quaternion r1 = invBaseLinkPose.rotation * delta;
        Quaternion rotationDeltaInBaseFrame = r1 * BaseLink.transform.rotation;
        Quaternion newRotationInBaseFrame = 
            rotationDeltaInBaseFrame * currentTipPose.rotation;
        newRotationInBaseFrame.Normalize();

        Quaternion newRotationInWorldFrame = BaseLink.transform.rotation 
            * newRotationInBaseFrame;
        return (newRotationInBaseFrame, newRotationInWorldFrame);
    }

    public void MoveTip(
        Vector3 positionDelta, Vector3 rotationDelta, float absoluteJawDesired)
    {
        (Vector3 newPos, Vector3 newPosWorld) = CalculateMoveTipPosition(positionDelta);
        (Quaternion newRot, Quaternion newRotWorld) = CalculateMoveTipRotation(rotationDelta);

        float newJawAngle = absoluteJawDesired;

        if (jawEnabled)
        {
            newJawAngle = ControllerUtils.ConvertRange(
                newJawAngle, -1, 1, MinJawAngleRadians, MaxJawAngleRadians);
            
            float jawDelta = newJawAngle - currentJawAngle;
            float absJawDelta = Mathf.Abs(jawDelta);
            float directionUnit = jawDelta / absJawDelta;
            
            if(absJawDelta > JawMaxInterpolationSpeedRad)
            {
                newJawAngle = directionUnit * JawMaxInterpolationSpeedRad + currentJawAngle;
            }
        }
        
        string[] jointNames = GetActiveJointNames();
        float[] jointValues = new float[jointNames.Length];

        Pose convertedPose = ConvertUnityPose(new Pose(newPos, newRot));
        float[] jointPositions = kinematics.ComputeIK(
            convertedPose.position,
            convertedPose.rotation);

        for (int i = 0; i < jointPositions.Length; i++)
        {
            jointValues[i] = jointPositions[i];
        }

        if (jawEnabled)
        {
            jointValues[jointValues.Length - 1] = newJawAngle;
        }

        jointController.UpdateJointCommands(jointNames, jointValues);

        currentTipPose = new Pose(newPos, newRot);
        currentTipPosewrtWorld = new Pose(newPosWorld, newRotWorld);
        currentJawAngle = newJawAngle;
    }

    public RobotSignal GetCartesianSignalFromPrimitive(
        int primitiveIndex, List<float> primitiveParams)
    {
        RobotSignal robotSignal = new RobotSignal();

        if (primitiveIndex >= PrimitiveLibrary.Count)
        {
            Debug.LogError("Primitive index not supported: " + primitiveIndex.ToString());
            return robotSignal;
        }

        if (currentPrimitive == null)
        {
            switch (PrimitiveLibrary[primitiveIndex])
            {
                case MotionPrimitiveType.Atomic:
                    currentPrimitive = new AtomicPrimitive(primitiveParams);
                    break;
                case MotionPrimitiveType.Move:
                    currentPrimitive = new StraightMovePrimitive(primitiveParams);
                    break;
                case MotionPrimitiveType.Cut:
                    currentPrimitive = new CutPrimitive(primitiveParams);
                    break;
                default:
                    Debug.LogError(
                        "Primitive type not supported: " +
                        PrimitiveLibrary[primitiveIndex].ToString());
                    break;
            }
        }

        robotSignal.PositionSignal = currentPrimitive.GetPositionAction();
        robotSignal.RotationSignal = currentPrimitive.GetRotationAction();
        robotSignal.JawSignal = currentPrimitive.GetGripperAction();

        return robotSignal;
    }

    public bool CheckPrimitiveComplete() {
        if (currentPrimitive == null) return true;
        if (currentPrimitive.CheckComplete(new List<float>{jointController.GetJawAngleRadians()}))
        {
            currentPrimitive = null;
            return true;
        }
        else return false;
    }

    public Pose ConvertUnityPose(Pose pose)
    {
        switch (axisConversion)
        {
            case AxisConversionMode.Urdf:
                return new Pose(
                    ControllerUtils.Unity2Ros(pose.position),
                    ControllerUtils.Unity2Ros(pose.rotation));
            case AxisConversionMode.Mujoco:
                return new Pose(
                    ControllerUtils.Unity2Mujoco(pose.position),
                    ControllerUtils.Unity2MujocoQuat(pose.rotation));
            default:
                return pose;
        }
    }

    public Pose ConvertRobotPose(Pose pose)
    {
        switch (axisConversion)
        {
            case AxisConversionMode.Urdf:
                return new Pose(
                    ControllerUtils.Ros2Unity(pose.position),
                    ControllerUtils.Ros2Unity(pose.rotation));
            case AxisConversionMode.Mujoco:
                return new Pose(
                    ControllerUtils.Mujoco2Unity(pose.position),
                    ControllerUtils.Mujoco2UnityQuat(pose.rotation));
            default:
                return pose;
        }
    }

    public Vector3 GetStartTipPosition() 
    {
        return startTipPose.position;
    }

    public Vector3 GetCurrentTipPosition() 
    {
        return currentTipPose.position;
    }

    public Quaternion GetStartTipRotation() 
    {
        return startTipPose.rotation;
    }

    public Quaternion GetCurrentTipRotation() 
    {
        return currentTipPose.rotation;
    }

    public Pose GetCurrentTipPosewrtWorld()
    {
        return currentTipPosewrtWorld;
    }

    public Pose GetCurrentTipPosewrtBase()
    {
        return currentTipPose;
    }

    public void SetMinJawAngleRadians(float min)
    {
        MinJawAngleRadians = min;
    }
    public void SetMaxJawAngleRadians(float max)
    {
        MaxJawAngleRadians = max;
    }

    public Vector3 GetReferenceRotation()
    {
        return referenceRotation;
    }

    public string[] GetActiveJointNames() 
    {
        return jointController.GetActiveJointNames();
    }

    public float GetJointCommand(string jointName)
    {
        return jointController.GetCurrentJointPosition(jointName);
    }

    public float GetCurrentJointPosition(string jointName)
    {
        return jointController.GetCurrentJointPosition(jointName);
    }

    public float[] GetCurrentJointPositions()
    {
        return jointController.GetCurrentJointPositions();
    }

    public void UpdateJointCommand(string jointName, float jointPosition)
    {
        jointController.UpdateJointCommand(jointName, jointPosition);
    }

    public void UpdateJointCommands(string[] jointNames, float[] jointPositions)
    {
        jointController.UpdateJointCommands(jointNames, jointPositions);
    }

    public ArticulationJointType GetJointType(string jointName)
    {
        return jointController.GetJointType(jointName);
    }

    public Vector2 GetJointLimit(string jointName)
    {
        return jointController.GetJointLimit(jointName);
    }

    public float GetJawAngleDegrees()
    {
        return jointController.GetJawAngleDegrees();
    }

    public float GetJawAngleRadians()
    {
        return jointController.GetJawAngleRadians();
    }
}
