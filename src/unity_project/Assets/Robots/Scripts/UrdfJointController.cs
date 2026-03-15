using System.Collections.Generic;
using System.Linq;
using UnityEngine;
using Unity.Robotics.UrdfImporter;
using System;

public struct UrdfJointMapping
{
    public ArticulationBody Joint;
    public UrdfJoint UrdfJoint;
    public UrdfJointMapping(ArticulationBody joint, UrdfJoint urdfJoint)
    {
        Joint = joint;
        UrdfJoint = urdfJoint;
    }
};

public class UrdfJointController : JointController
{
    public float MainP = 160000;
    public float MainI = 0.0f;
    public float MainD = 25000f;
    public float ToolP = 100000f;
    public float ToolI = 0.0f;
    public float ToolD = 10000f;
    public float ForceLimit = 1e+07f;
    public bool UseGravity = false;

    [NonSerialized]
    public bool isCollisionDetected;
    private bool jawOpen;
    private float angleOfContact;
    
    private Dictionary<string, UrdfJointMapping> jointNameToActiveJoint;
    private List<MimicJointControl> mimicJointControls = new List<MimicJointControl>();
    private const int xAxis = 0;
    private const float defDyanmicVal = 0.05f;
    private const float defMimicDynamicVal = 0.05f;
    
    public override void Initialize()
    {
        isCollisionDetected = false;
        jawOpen = false;
        angleOfContact = 58f;

        Vector3 localScaleVec = this.transform.localScale;
        if (!Mathf.Approximately(localScaleVec.x, localScaleVec.y) ||
            !Mathf.Approximately(localScaleVec.y, localScaleVec.z) ||
            !Mathf.Approximately(localScaleVec.z, localScaleVec.x))
        {
            Debug.LogError("Object transform.scale.xyz must be equal!");
            return;
        }
        float scale = localScaleVec.x;

        jointNameToActiveJoint = new Dictionary<string, UrdfJointMapping>();
        UrdfJoint[] urdfJoints = GetComponentsInChildren<UrdfJoint>();

        bool isToolJoint = false;
        foreach (UrdfJoint urdfJoint in urdfJoints)
        {
            // Joints should be ordered from root to leaf on a tree
            // So everything after insertion is a tool joint
            if (urdfJoint.jointName.Contains("insertion")) isToolJoint = true;

            // Don't use this API too much because not supported by urdf_importer
            ArticulationBody joint = urdfJoint.unityJoint;
            if (urdfJoint.JointType == UrdfJoint.JointTypes.Fixed) continue;

            if (urdfJoint.hasMimic)
            {
                UrdfJoint mimicedJoint = Array.Find(
                    urdfJoints, u => u.jointName == urdfJoint.mimicedJoint);
                
                if (mimicedJoint == null)
                {
                    Debug.LogError(
                        "Mimiced joint [" + urdfJoint.mimicedJoint + "] not found!");
                    return;
                }

                float mimicedStartJointPosition = 0.0f;
                if (Array.Exists(StartJointPositions, u => u.Name == mimicedJoint.jointName))
                {
                    var startJointPosition = Array.Find(
                        StartJointPositions, u => u.Name == mimicedJoint.jointName);
                    mimicedStartJointPosition = startJointPosition.Position;
                }

                MimicJointControl mimicJointControl = joint.gameObject.AddComponent<MimicJointControl>();
                mimicJointControl.SetMimic(
                    mimicedJoint,
                    (float)urdfJoint.mimicMultiplier,
                    (float)urdfJoint.mimicOffset,
                    mimicedStartJointPosition);
                
                mimicJointControls.Add(mimicJointControl);
                joint.jointFriction = defMimicDynamicVal;
                joint.angularDamping = defMimicDynamicVal;
                joint.linearDamping = defMimicDynamicVal;
            }
            else // Is an active joint
            {
                joint.jointFriction = defDyanmicVal;
                joint.angularDamping = defDyanmicVal;
                joint.linearDamping = defDyanmicVal;
                jointNameToActiveJoint[urdfJoint.jointName] = new UrdfJointMapping(joint, urdfJoint);
            }

            ArticulationDrive currentDrive = joint.xDrive;
            currentDrive.stiffness = isToolJoint ? ToolP : MainP;
            currentDrive.damping = isToolJoint ? ToolD : MainD;
            currentDrive.forceLimit = ForceLimit;

            if (urdfJoint.JointType == UrdfJoint.JointTypes.Prismatic)
            {
                currentDrive.upperLimit = currentDrive.upperLimit * scale;
                currentDrive.lowerLimit = currentDrive.lowerLimit * scale;
                // This will not get larger after every start
            }
            joint.xDrive = currentDrive;
        }

        // Setup current joint position command
        activeJointNames = new string[jointNameToActiveJoint.Count];
        lock (jointPositionLock)
        {
            for (int i = 0; i < jointNameToActiveJoint.Count; i++)
            {
                var jointName = jointNameToActiveJoint.ElementAt(i).Key;
                try
                {
                    var startJointPosition = Array.Find(
                        StartJointPositions, u => u.Name == jointName);
                    currentJointPositionCmd.Add(jointName, startJointPosition.Position);
                }
                catch
                {
                    currentJointPositionCmd.Add(jointName, 0.0f);
                }
                activeJointNames[i] = jointName;
                if (jointName == "jaw")
                {
                    jawDetected = true;
                }
            }
            startJointPositionCmd = new Dictionary<string, float>(currentJointPositionCmd);
        }
        // MimicJointControl will call it's own TeleportSetJointPositions at it's own start
        TeleportSetJointPositions(startJointPositionCmd);
        SetUseGravity();
    }

    private void TeleportSetJointPositions(Dictionary<string, float> jointPositionCmd)
    {
        foreach (var item in jointPositionCmd)
        {
            var jp = jointNameToActiveJoint[item.Key].Joint.jointPosition;
            jp[xAxis] = item.Value;
            jointNameToActiveJoint[item.Key].Joint.jointPosition = jp;

            UrdfJointMapping jointMapping = jointNameToActiveJoint[item.Key];
            float newTarget = item.Value;
            if (jointMapping.UrdfJoint.IsRevoluteOrContinuous)
            {
                newTarget = newTarget * Mathf.Rad2Deg;
            }
            //else is prismatic, so dont convert to deg, as it should be in m
            ArticulationDrive currentDrive = jointMapping.Joint.xDrive;
            currentDrive.target = newTarget;
            jointMapping.Joint.xDrive = currentDrive;
        }
    }
    
    private void SetUseGravity()
    {
        foreach (ArticulationBody ar in GetComponentsInChildren<ArticulationBody>())
            ar.useGravity = UseGravity;
    }

    public override void ResetToStartJointPositions()
    {
        lock (jointPositionLock)
        {
            // Set Targets to startJointPositionCmd (will do in FixedUpdate)
            currentJointPositionCmd = new Dictionary<string, float>(startJointPositionCmd);
        }
        TeleportSetJointPositions(startJointPositionCmd);
        foreach (var mimicJointControl in mimicJointControls)
        {
            mimicJointControl.TeleportSetToStartJointPosition();
        }
    }

    public override bool ResetToJointPositions(string[] activeJointNames, float[] positionCommands)
    {
        Dictionary<string, float> new_position_cmd;
        new_position_cmd = new Dictionary<string, float>(startJointPositionCmd);
        for (int i = 0; i < activeJointNames.Length; i++)
        {
            if (!currentJointPositionCmd.ContainsKey(activeJointNames[i]))
            {
                Debug.Log("ERROR: Joint name [" + activeJointNames[i] + "] is not found in active joint chain");
                return false;
            }
            new_position_cmd[activeJointNames[i]] = positionCommands[i];
        }

        lock (jointPositionLock)
        {
            currentJointPositionCmd = new_position_cmd;
        }
        TeleportSetJointPositions(new_position_cmd);
        foreach (var mimicJointControl in mimicJointControls)
        {
            mimicJointControl.TeleportSetToMatchJointPosition();
        }
        return true;
    }

    public override float GetCurrentJointPosition(string jointName)
    {
        UrdfJointMapping joint = jointNameToActiveJoint[jointName];
        float jointPosition = joint.UrdfJoint.GetPosition();
        return jointPosition;
    }


    public override float GetJointVelocity(string jointName)
    {
        UrdfJointMapping joint = jointNameToActiveJoint[jointName];
        float jointPosition = joint.UrdfJoint.GetVelocity();
        return (float)Math.Round(jointPosition);
    }

    public override float[] GetCurrentJointPositions()
    {
        return GetCurrentJointPositions(jointNameToActiveJoint.Count);
    }

    public override float[] GetCurrentJointPositions(int upTo)
    {
        float[] currentJointPositions = new float[upTo];
        for (int i = 0; i < upTo; i++)
        {
            var item = jointNameToActiveJoint.ElementAt(i);
            currentJointPositions[i] = item.Value.UrdfJoint.GetPosition();
        }
        return currentJointPositions;
    }

    public override Vector2 GetJointLimit(string jointName)
    {
        UrdfJointMapping joint = jointNameToActiveJoint[jointName];
        float mul = joint.UrdfJoint.IsRevoluteOrContinuous ? Mathf.Deg2Rad : 1;
        return new Vector2(
            joint.UrdfJoint.unityJoint.xDrive.lowerLimit * mul,
            joint.UrdfJoint.unityJoint.xDrive.upperLimit * mul);
    }

    public override ArticulationJointType GetJointType(string jointName)
    {
        UrdfJointMapping joint = jointNameToActiveJoint[jointName];
        return joint.UrdfJoint.unityJoint.jointType;
    }

    public Dictionary<string, UrdfJointMapping> GetJointMapping()
    {
        return jointNameToActiveJoint;
    }

    public void SetJointMapping(string jointName, UrdfJointMapping value)
    {
        jointNameToActiveJoint[jointName] = value;
    }

    public void SetJawOpen(bool status)
    {
        jawOpen = status;
    }
    public bool GetJawOpen()
    {
        return jawOpen;
    }

    public void SetAngleOfContact(float angle)
    {
        angleOfContact = angle;
    }

    public float GetAngleOfContact()
    {
        return angleOfContact;
    }

    public void FixedUpdate()
    {
        // Update to the new joint position command
        lock (jointPositionLock)
        {
            foreach (var item in currentJointPositionCmd)
            {
                UrdfJointMapping jointMap = jointNameToActiveJoint[item.Key];
                float newTarget = item.Value;
                if (jointMap.UrdfJoint.IsRevoluteOrContinuous)
                {
                    newTarget = newTarget * Mathf.Rad2Deg;
                }
                //else is prismatic, so dont convert to deg, as it should be in m
                ArticulationDrive currentDrive = jointMap.Joint.xDrive;
                if (item.Key == "jaw" && isCollisionDetected && !jawOpen)
                {
                    // Jaw is closed during collision, do nothing as JawCollision.cs handles it
                    return;
                }

                currentDrive.target = newTarget;
                jointMap.Joint.xDrive = currentDrive;
            }
        }
    }
}
