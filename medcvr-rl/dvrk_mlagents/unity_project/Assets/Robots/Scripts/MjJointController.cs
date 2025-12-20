using System;
using System.Collections.Generic;
using System.Linq;
using Mujoco;
using UnityEngine;

public class MjJointController : JointController
{
    public GameObject Actuators;
    public GameObject BaseLink;
    
    private Dictionary<string, MjActuator> jointNameToMjActuator;
    private Dictionary<string, MjBaseJoint> jointNameToMjBaseJoint;

    public override void Initialize()
    {
        jointNameToMjActuator = new Dictionary<string, MjActuator>();
        jointNameToMjBaseJoint = new Dictionary<string, MjBaseJoint>();
        MjActuator[] mjActuators = Actuators.GetComponentsInChildren<MjActuator>();
        MjBaseJoint[] mjBaseJoints = BaseLink.GetComponentsInChildren<MjBaseJoint>();

        foreach (MjActuator mjActuator in mjActuators)
        {
            jointNameToMjActuator[mjActuator.Joint.GetComponent<MjBaseJoint>().name] = mjActuator;
        }

        foreach (MjBaseJoint mjBaseJoint in mjBaseJoints)
        {
            jointNameToMjBaseJoint[mjBaseJoint.name] = mjBaseJoint;
        }

        // Setup current and start joint position command
        activeJointNames = new string[jointNameToMjActuator.Count];
        lock (jointPositionLock)
        {
            for (int i = 0; i < jointNameToMjActuator.Count; i++)
            {
                var jointName = jointNameToMjActuator.ElementAt(i).Key;
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

        TeleportSetJointPositions(startJointPositionCmd);
    }

    private unsafe void TeleportSetJointPositions(Dictionary<string, float> jointPositionCmd)
    {
        if (MjScene.Instance.Data == null)
        {
            Debug.Log("Warning: Mujoco scene data was initialized manually!");
            MjScene.Instance.CreateScene();
        }

        for (int i = 0; i < jointNameToMjBaseJoint.Count; i++)
        {
            string jointName = jointNameToMjBaseJoint.ElementAt(i).Key;
            int qPosAddress = jointNameToMjBaseJoint[jointName].QposAddress;

            if (jointPositionCmd.ContainsKey(jointName))
            {
                MjScene.Instance.Data->qpos[qPosAddress] = jointPositionCmd[jointName];
                MjScene.Instance.Data->qvel[qPosAddress] = 0.0;
            }
            else
            {
                MjScene.Instance.Data->qpos[qPosAddress] = 0.0;
                MjScene.Instance.Data->qvel[qPosAddress] = 0.0;
            }
        }

        foreach (var item in jointPositionCmd)
        {
            if (jointNameToMjActuator.ContainsKey(item.Key))
            {
                jointNameToMjActuator[item.Key].Control = item.Value;
            }
        }

        MjScene.Instance.SyncUnityToMjState();
    }
    

    public override void ResetToStartJointPositions()
    {
        lock (jointPositionLock)
        {
            currentJointPositionCmd = new Dictionary<string, float>(startJointPositionCmd);
        }
        TeleportSetJointPositions(startJointPositionCmd);
    }

    public override bool ResetToJointPositions(string[] activeJointNames, float[] positionCommands)
    {
        Dictionary<string, float> newPositionCmd;
        newPositionCmd = new Dictionary<string, float>(startJointPositionCmd);
        for (int i = 0; i < activeJointNames.Length; i++)
        {
            if (!currentJointPositionCmd.ContainsKey(activeJointNames[i]))
            {
                Debug.Log("ERROR: Joint name [" + activeJointNames[i] + "] is not found in active joint chain");
                return false;
            }
            newPositionCmd[activeJointNames[i]] = positionCommands[i];
        }

        lock (jointPositionLock)
        {
            currentJointPositionCmd = newPositionCmd;
        }
        TeleportSetJointPositions(newPositionCmd);
        return true;
    }

    public unsafe override float GetCurrentJointPosition(string jointName)
    {
        if (jointNameToMjBaseJoint.ContainsKey(jointName))
        {
            return (float)MjScene.Instance.Data->qpos[
                jointNameToMjBaseJoint[jointName].QposAddress];
        }
        else
        {
            Debug.Log("ERROR: Joint name [" + jointName + "] was not found!");
            return 0.0f;
        }
    }


    public unsafe override float GetJointVelocity(string jointName)
    {
        if (jointNameToMjBaseJoint.ContainsKey(jointName))
        {
            return (float)MjScene.Instance.Data->qvel[
                jointNameToMjBaseJoint[jointName].QposAddress];
        }
        else
        {
            Debug.Log("ERROR: Joint name [" + jointName + "] was not found!");
            return 0.0f;
        }
    }

    public override float[] GetCurrentJointPositions()
    {
        return GetCurrentJointPositions(jointNameToMjActuator.Count);
    }

    public override float[] GetCurrentJointPositions(int upTo)
    {
        float[] currentJointPositions = new float[upTo];
        for (int i = 0; i < upTo; i++)
        {
            string name = jointNameToMjActuator.ElementAt(i).Key;
            currentJointPositions[i] = GetCurrentJointPosition(name);
        }
        return currentJointPositions;
    }

    public override Vector2 GetJointLimit(string jointName)
    {
        return jointNameToMjActuator[jointName].CommonParams.CtrlRange;
    }

    public override ArticulationJointType GetJointType(string jointName)
    {
        if (jointNameToMjBaseJoint[jointName].GetType() == typeof(MjHingeJoint))
            return ArticulationJointType.RevoluteJoint;
        else if (jointNameToMjBaseJoint[jointName].GetType() == typeof(MjSlideJoint))
            return ArticulationJointType.PrismaticJoint;
        else
            return ArticulationJointType.FixedJoint;
    }

    public void FixedUpdate()
    {
        lock (jointPositionLock)
        {
            foreach (var item in currentJointPositionCmd)
            {
                if (jointNameToMjActuator.ContainsKey(item.Key))
                {
                    jointNameToMjActuator[item.Key].Control = item.Value;
                }
            }
        }
    }
}
