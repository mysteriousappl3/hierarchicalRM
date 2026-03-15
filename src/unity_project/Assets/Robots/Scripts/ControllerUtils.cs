using UnityEngine;

public class ControllerUtils
{
    public static Vector3 Ros2Unity(Vector3 vector3)
    {
        return new Vector3(-vector3.y, vector3.z, vector3.x);
    }

    public static Vector3 Unity2Ros(Vector3 vector3)
    {
        return new Vector3(vector3.z, -vector3.x, vector3.y);
    }

    public static Vector3 Ros2UnityScale(Vector3 vector3)
    {
        return new Vector3(vector3.y, vector3.z, vector3.x);
    }

    public static Vector3 Unity2RosScale(Vector3 vector3)
    {
        return new Vector3(vector3.z, vector3.x, vector3.y);
    }

    public static Quaternion Ros2Unity(Quaternion quaternion)
    {
        return new Quaternion(quaternion.y, -quaternion.z, -quaternion.x, quaternion.w);
    }

    public static Quaternion Unity2Ros(Quaternion quaternion)
    {
        return new Quaternion(-quaternion.z, quaternion.x, -quaternion.y, quaternion.w);
    }

    public static Vector3 Unity2Mujoco(Vector3 vector3)
    {
        return new Vector3(vector3.x, vector3.z, vector3.y);
    }

    public static Quaternion Unity2MujocoQuat(Quaternion quaternion)
    {
        return new Quaternion(w:-quaternion.w, x:quaternion.x, y:quaternion.z, z:quaternion.y);
    }

    public static Vector3 Mujoco2Unity(Vector3 vector3)
    {
        return new Vector3(vector3.x, vector3.z, vector3.y);
    }

    public static Quaternion Mujoco2UnityQuat(Quaternion quaternion)
    {
        return new Quaternion(w:-quaternion.w, x:quaternion.x, y:quaternion.z, z:quaternion.y);
    }

    public static Pose ConvertMatToPose(Matrix4x4 mat)
    {
        Pose pose = new Pose
        {
            position = mat.GetColumn(3),
            rotation = QuaternionFromMatrix(mat)
        };
        return pose;
    }

    // Transform pose using the inverse refPose
    public static Pose TransformPose(Pose pose, Pose refPose)
    {
        // Assumes all poses are already in same coordinate system!
        Pose newPose = Pose.identity;
        newPose.position = refPose.position + 
            refPose.rotation * pose.position;
        newPose.rotation = refPose.rotation * pose.rotation;
        return newPose;
    }

    // Transform pose to be in basis of refPose
    public static Pose TransformWorldToLocal(Pose pose, Pose basisPose)
    {
        Quaternion invRefRot = Quaternion.Inverse(basisPose.rotation);
        Vector3 localPosition = invRefRot * (pose.position - basisPose.position);
        Quaternion localRotation = invRefRot * pose.rotation;
        return new Pose(localPosition, localRotation);
    }

    public static Quaternion QuaternionFromMatrix(Matrix4x4 m) {
        // Adapted from: http://www.euclideanspace.com/maths/geometry/rotations/conversions/matrixToQuaternion/index.htm
        Quaternion q = new Quaternion();
        q.w = Mathf.Sqrt( Mathf.Max( 0, 1 + m[0,0] + m[1,1] + m[2,2] ) ) / 2; 
        q.x = Mathf.Sqrt( Mathf.Max( 0, 1 + m[0,0] - m[1,1] - m[2,2] ) ) / 2; 
        q.y = Mathf.Sqrt( Mathf.Max( 0, 1 - m[0,0] + m[1,1] - m[2,2] ) ) / 2; 
        q.z = Mathf.Sqrt( Mathf.Max( 0, 1 - m[0,0] - m[1,1] + m[2,2] ) ) / 2; 
        q.x *= Mathf.Sign( q.x * ( m[2,1] - m[1,2] ) );
        q.y *= Mathf.Sign( q.y * ( m[0,2] - m[2,0] ) );
        q.z *= Mathf.Sign( q.z * ( m[1,0] - m[0,1] ) );
        return q;
    }

    public static float ConvertRange(
        float value, float oldMin, float oldMax, float newMin, float newMax)
    {
        float oldRange = oldMax - oldMin;
        float newRange = newMax - newMin;
        float newValue = (((value - oldMin) * newRange ) / oldRange) + newMin;
        return newValue;
    }
}
