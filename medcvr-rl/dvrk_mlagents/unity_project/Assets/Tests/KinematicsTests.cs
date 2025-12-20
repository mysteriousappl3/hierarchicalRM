using NUnit.Framework;
using UnityEngine;

public class KinematicsTests
{

    [Test]
    [TestCase(new float[] {0, 0, 0.12f, 0, 0, 0})]
    [TestCase(new float[] {0.52f, -0.13f, 0.12f, 0.89f, 0.234f, -0.73f})]
    public void PSMKinematicsTestLoop(float[] injp)
    {
        RobotController.ToolAttachment tool = RobotController.ToolAttachment.LargeNeedleDriver;
        PSMKinematics kinematics = new PSMKinematics(
            new PSMKinematicParameters(tool));
        
        // Test the forward kinematics
        Matrix4x4 mat = kinematics.ComputeFK(injp, kinematics.GetNumberOfLinks());
        
        Vector3 position = mat.GetColumn(3);
        Debug.Log("position: " + position);
        Quaternion rotation = ControllerUtils.QuaternionFromMatrix(mat);
        Debug.Log("rotation: " + rotation.eulerAngles);

        // Test the inverse kinematics
        float[] outjp = kinematics.ComputeIK(position, rotation);
        Debug.Log("outjp: " + string.Join(", ", outjp));

        for (int i = 0; i < outjp.Length; i++)
        {
            UnityEngine.Assertions.Assert.AreApproximatelyEqual(injp[i], outjp[i], 0.0001f);
        }
    }

    [Test]
    [TestCase(0f, 0.0125f, .09f, 0f, 0f, 180f)]
    [TestCase(-0.03f, 0.013f, .07f, -12f, 47f, 167f)]
    public void FrankaKinematicsTestLoop(float px, float py, float pz, float rx, float ry, float rz)
    {
        RobotController.ToolAttachment tool = RobotController.ToolAttachment.LargeNeedleDriver;
        FrankaKinematics kinematics = new FrankaKinematics(
            new FrankaKinemticsParameters(tool),
            new Vector3(0.3f, 0f, 0.2815f));
        
        kinematics.SetInitialJointValues(new float[]{0, -0.6f, 0, -2.32f, 0, 1.77f, 0});

        Vector3 inpos = new Vector3(px, py, pz);
        Quaternion inrot = Quaternion.Euler(rx, ry, rz);
        
        // Test the inverse kinematics
        float[] outjp = kinematics.ComputeIK(inpos, inrot);
        

        // Test the inverse kinematics
        Matrix4x4 mat = kinematics.ComputeFK(outjp, kinematics.GetNumberOfLinks());
        
        Vector3 position = mat.GetColumn(3);
        Quaternion rotation = ControllerUtils.QuaternionFromMatrix(mat);

        Debug.Log("position: " + position);
        Debug.Log("rotation: " + rotation.eulerAngles);

        UnityEngine.Assertions.Assert.AreApproximatelyEqual(inpos.x, position.x, 0.01f);
        UnityEngine.Assertions.Assert.AreApproximatelyEqual(inpos.y, position.y, 0.01f);
        UnityEngine.Assertions.Assert.AreApproximatelyEqual(inpos.z, position.z, 0.01f);
        UnityEngine.Assertions.Assert.AreApproximatelyEqual(Mathf.Abs(inrot.x), Mathf.Abs(rotation.x), 0.01f);
        UnityEngine.Assertions.Assert.AreApproximatelyEqual(Mathf.Abs(inrot.y), Mathf.Abs(rotation.y), 0.01f);
        UnityEngine.Assertions.Assert.AreApproximatelyEqual(Mathf.Abs(inrot.z), Mathf.Abs(rotation.z), 0.01f);
    }

    
    [Test]
    [TestCase(0f, 0.0125f, .09f, 0f, 0f, 180f)]
    [TestCase(-0.03f, 0.013f, .07f, -12f, 47f, 167f)]
    [TestCase(0.05f, 0.011f, -0.02f, -30f, 17f, 173f)]
    public void FrankaLibOutput(float px, float py, float pz, float rx, float ry, float rz)
    {
        RobotController.ToolAttachment tool = RobotController.ToolAttachment.LargeNeedleDriver;
        FrankaKinematics kinematics = new FrankaKinematics(
            new FrankaKinemticsParameters(tool),
            new Vector3(0.3f, 0f, 0.2815f));
        
        kinematics.SetInitialJointValues(new float[]{0, -0.6f, 0, -2.32f, 0, 1.77f, 0});

        Vector3 inpos = new Vector3(px, py, pz);
        Quaternion inrot = Quaternion.Euler(rx, ry, rz);
        
        float[] outjp = kinematics.ComputeIK(inpos, inrot);


        Matrix4x4 targetPose = Matrix4x4.TRS(
            inpos, inrot, Vector3.one);
        Debug.Log("targetPose: " + targetPose);
        Debug.Log("outjp: " + string.Join(", ", outjp));

        UnityEngine.Assertions.Assert.AreApproximatelyEqual(1.0f, 1.0f, 0.01f);
    }
}
