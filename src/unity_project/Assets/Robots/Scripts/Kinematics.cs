using System;
using System.Collections.Generic;
using UnityEngine;

public static class Global
{
    public static float PI_2 = Mathf.PI/2;
}

public class Dh
{
    public enum JointType
    {
        REVOLUTE = 0,
        PRISMATIC = 1
    }

    public enum Convention
    {
        STANDARD = 0,
        MODIFIED = 1
    }
    private readonly float alpha;
    private readonly float a;
    private readonly float d;
    private readonly float offset;
    private readonly JointType jointType;

    /*
    Note: Currently only uses Modified Convention
    Units:
    alpha: radians
    a: m
    d: m
    offset: m for PRISMATIC, radians for revolute
    */
    public Dh(float alpha,
        float a,
        float d,
        float offset,
        JointType jointType)
    {
        this.alpha = alpha;
        this.a = a;
        this.d = d;
        this.offset = offset;
        if (jointType == JointType.PRISMATIC)
        {
            this.offset = offset;
        }
        this.jointType = jointType;
        if (jointType != JointType.REVOLUTE &&
            jointType != JointType.PRISMATIC)
        {
            throw new InvalidOperationException("jointType must be PRISMATIC or REVOLUTE");
        }
    }

    // theta: m for PRISMATIC, Rad for revolute 
    public Matrix4x4 ToMat(float theta = 0.0f)
    {
        float ca = MathF.Cos(alpha);
        float sa = MathF.Sin(alpha);
        float th = 0.0f;
        float local_d = d;
        if (jointType == JointType.REVOLUTE){
            th = theta + offset;
        }
        else if (jointType == JointType.PRISMATIC){
            local_d = local_d + offset + theta;
        }
        float ct = MathF.Cos(th);
        float st = MathF.Sin(th);

        Matrix4x4 newMat = new Matrix4x4();
        newMat.SetRow(0, new Vector4(     ct,     -st, 0.0f,       a));
        newMat.SetRow(1, new Vector4(st * ca, ct * ca,  -sa, -local_d * sa));
        newMat.SetRow(2, new Vector4(st * sa, ct * sa,   ca,  local_d * ca));
        newMat.SetRow(3, new Vector4(   0.0f,    0.0f, 0.0f,      1f));

        return newMat;
    }
}

public class Kinematics
{
    protected List<Dh> dhChain;
    protected int numLinks = 7;

    public Dh GetDh(int linkIndex)
    {
        if(linkIndex >= numLinks)
        {
            Debug.LogError("linkNum must be < numLinks");
        }
        return dhChain[linkIndex];
    }

    public int GetNumberOfLinks()
    {
        return numLinks;
    }

    public virtual Matrix4x4 ComputeFK(float[] jointPositions, int upToLink = 7)
    {
        Matrix4x4 returnTransform = Matrix4x4.identity;
        if(jointPositions.Length > numLinks || 
           jointPositions.Length > upToLink)
        {
            Debug.LogError("Number of joint positions must be < " + numLinks);
        }

        for(int i = 0; i < jointPositions.Length; i++)
        {
            returnTransform = returnTransform * GetDh(i).ToMat(jointPositions[i]);
        }
        for(int i = jointPositions.Length; i < upToLink; i++)
        {
            returnTransform = returnTransform * GetDh(i).ToMat(0.0f);
        }

        return returnTransform;
    }

    public virtual float[] ComputeIK(Matrix4x4 targetPose) 
    {
        Debug.LogWarning("ComputeIK Not Implemented");
        return new float[0];
    }

    public float[] ComputeIK(Vector3 targetPosition, Quaternion targetRotation)
    {
        Matrix4x4 targetPose = Matrix4x4.TRS(
            targetPosition, targetRotation, Vector3.one);
        return ComputeIK(targetPose);
    }

    public static float GetAngle(
        Vector3 vecA,
        Vector3 vecB,
        bool useUpVec = false,
        Vector3 upVec = new Vector3())
    {
        vecA = vecA.normalized;
        vecB = vecB.normalized;

        Vector3 crossAB =  Vector3.Cross(vecA, vecB);
        float vDot = Vector3.Dot(vecA, vecB);

        float angle = 0.0f;
        if (1.0f - vDot < 0.000001f) angle = 0.0f;
        else if (1.0f + vDot < 0.000001) angle = MathF.PI;
        else angle = MathF.Acos(vDot);

        // Check same direction
        if (useUpVec && MathF.Sign(Vector3.Dot(crossAB, upVec)) < 0.0f)
        {
            angle = -angle;
        }

        return angle;
    }

    public static Vector3 GetUpper3OfColumn(Matrix4x4 Mat, int i)
    {
        return new Vector3(
            Mat[0, i],
            Mat[1, i],
            Mat[2, i]);
    }

    public void PrintFloatArray(float[] arr)
    {
        string s = string.Join(", ", arr);
        Debug.Log(s);
        return;
    }

    public void PrintMatrixPosRot(Matrix4x4 mat, string name = "")
    {
        Debug.Log(name + " Position: " + GetUpper3OfColumn(mat, 3) + 
                  " Rotation: " + mat.rotation.eulerAngles.ToString());
    }
}
