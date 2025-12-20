using System;
using System.Collections.Generic;
using UnityEngine;

public class JointController : MonoBehaviour
{
    [Header("Joint Parameters")]
    public JointPosition[] StartJointPositions;
    
    [Serializable]
    public struct JointPosition
    {
        public string Name;
        public float Position;
    };
    
    protected string[] activeJointNames;
    protected Dictionary<string, float> currentJointPositionCmd = new Dictionary<string, float>();
    protected Dictionary<string, float> startJointPositionCmd;
    protected readonly object jointPositionLock = new object();
    
    [HideInInspector]
    public bool jawDetected = false;

    public virtual void Initialize()
    {
    }

    public string[] GetActiveJointNames()
    {
        return activeJointNames;
    }

    public float GetStartJointPosition(string jointName)
    {
        float command = -1f;
        if (!startJointPositionCmd.ContainsKey(jointName))
        {
            Debug.Log("ERROR: [" + jointName + "] is not found in start joint position command");
            return command;
        }
        command = startJointPositionCmd[jointName];
        return command;
    }

    public virtual float GetCurrentJointPosition(string jointName)
    {
        return 0.0f;
    }

    public virtual float[] GetCurrentJointPositions()
    {
        return new float[0];
    }

    public virtual float[] GetCurrentJointPositions(int upToIndex)
    {
        return new float[0];
    }

    public virtual void SetJointPositions(float[] jointPositions)
    {
    }

    public virtual void SetJointPosition(string jointName, float position)
    {
    }

    public virtual void ResetToStartJointPositions()
    {
    }

    public virtual bool ResetToJointPositions(string[] jointNames, float[] jointPositions)
    {
        return false;
    }

    public bool UpdateJointCommands(string[] jointNames, float[] jointPositions)
    {
        for (int i = 0; i < activeJointNames.Length; ++i)
            if (!UpdateJointCommand(jointNames[i], jointPositions[i])) return false;
        return true;
    }

    public bool UpdateJointCommand(string activeJointName, float positionCommand)
    {
        if (!currentJointPositionCmd.ContainsKey(activeJointName))
        {
            Debug.Log("ERROR: Joint name [" + activeJointName + "] is not found in active joint chain");
            return false;
        }

        lock (jointPositionLock)
        {
            currentJointPositionCmd[activeJointName] = positionCommand;
        }
        return true;
    }

    public float GetJointCommand(string activeJointName)
    {
        float command = -1f;
        if (!currentJointPositionCmd.ContainsKey(activeJointName))
        {
            Debug.Log("ERROR: Joint name [" + activeJointName + "] is not found in active joint chain");
            return command;
        }

        lock (jointPositionLock)
        {
            command = currentJointPositionCmd[activeJointName];
        }
        return command;
    }

    public float[] GetFullJointCommand()
    {
        float[] jointCommand = new float[activeJointNames.Length];
        for (int i = 0; i < activeJointNames.Length; i++)
        {
            jointCommand[i] = GetJointCommand(activeJointNames[i]);
        }
        return jointCommand;
    }

    public virtual float GetJointVelocity(string jointName)
    {
        return 0.0f;
    }

    public virtual Vector2 GetJointLimit(string jointName)
    {
        return new Vector2(0.0f, 0.0f);
    }

    public virtual ArticulationJointType GetJointType(string jointName)
    {
        return ArticulationJointType.FixedJoint;
    }

    public float GetJawAngleRadians()
    {
        return GetCurrentJointPosition("jaw");
    }

    public float GetJawAngleDegrees()
    {
        return GetJawAngleRadians() * Mathf.Rad2Deg;
    }

}
