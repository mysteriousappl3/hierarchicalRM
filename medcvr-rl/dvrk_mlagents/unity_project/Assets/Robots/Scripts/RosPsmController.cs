using System;
using UnityEngine;
using Unity.Robotics.ROSTCPConnector;
using RosMessageTypes.Sensor;

public class RosController : MonoBehaviour
{
    public RobotController robotController;

    // ROS topic names
    public string MoveJPTopicName = "measured_js"; // Should be move_jp, but for now we hack it this way
    public string MeasuredJPTopicName = "feedback_measured_js"; // Should be measured_js, but already used
    public string TopicNameSpace = "PSM2";

    private string completeJPSubTopicName;
    private string completeJPPubTopicName;
    private string completeJawJPSubTopicName;
    private string completeJawJPPubTopicName;

    private JointStateMsg jsMsg;
    private JointStateMsg jawJsMsg;
    private ROSConnection rosNode;

    public void Start()
    {
        // Start the ROS connection last
        completeJPSubTopicName = TopicNameSpace + "/" + MoveJPTopicName;
        completeJawJPSubTopicName = TopicNameSpace + "/jaw/" + MoveJPTopicName;
        completeJPPubTopicName = TopicNameSpace + "/" + MeasuredJPTopicName;
        completeJawJPPubTopicName = TopicNameSpace + "/jaw/" + MeasuredJPTopicName;

        rosNode = ROSConnection.GetOrCreateInstance();
        rosNode.Subscribe<JointStateMsg>(completeJPSubTopicName, ReadNewJointPostition);
        rosNode.Subscribe<JointStateMsg>(completeJawJPSubTopicName, ReadNewJawJointPostition);
        rosNode.RegisterPublisher<JointStateMsg>(completeJPPubTopicName);
        rosNode.RegisterPublisher<JointStateMsg>(completeJawJPPubTopicName);

        jsMsg = new JointStateMsg();
        jawJsMsg = new JointStateMsg();

        string[] activeJointNames = robotController.GetActiveJointNames();
        var jsSize = activeJointNames.Length - 1;
        Array.Resize(ref jsMsg.name, jsSize);
        Array.Resize(ref jsMsg.position, jsSize);
        Array.Resize(ref jawJsMsg.name, 1);
        Array.Resize(ref jawJsMsg.position, 1);
        for (int i = 0; i < jsSize; i++)
        {
            jsMsg.name[i] = activeJointNames[i];
        }
        jawJsMsg.name[0] = activeJointNames[jsSize]; // TODO Use find if needed
    }

    float[] doubleToFLoat(double[] doubleArr)
    {
        float[] floatArr = new float[doubleArr.Length];
        for (int i = 0; i < doubleArr.Length; i++)
        {
            floatArr[i] = (float)doubleArr[i];
        }
        return floatArr;
    }


    void ReadNewJointPostition(JointStateMsg jointPositionCommand)
    {
        if (jointPositionCommand.name.Length != jointPositionCommand.position.Length)
        {
            Debug.Log("ERROR: Joint name and position needs to be same length");
            return;
        }
        robotController.UpdateJointCommands(jointPositionCommand.name, doubleToFLoat(jointPositionCommand.position));
    }

    void ReadNewJawJointPostition(JointStateMsg jointPositionCommand)
    {
        if (jointPositionCommand.name.Length == 0)
        {
            Debug.Log("ERROR: Joint name must be size 1");
            return;
        }
        if (jointPositionCommand.position.Length == 0)
        {
            Debug.Log("ERROR: Joint position must be size 1");
            return;
        }
        robotController.UpdateJointCommand(jointPositionCommand.name[0], (float)jointPositionCommand.position[0]);
    }

    void publishJointState()
    {
        float[] currentJP = robotController.GetCurrentJointPositions();
        for (int i = 0; i < currentJP.Length - 1; i++)
        {
            jsMsg.position[i] = currentJP[i];
        }
        jawJsMsg.position[0] = currentJP[currentJP.Length - 1]; // TODO Use find if needed
        rosNode.Publish(completeJPPubTopicName, jsMsg);
        rosNode.Publish(completeJawJPPubTopicName, jawJsMsg);
    }

    public void FixedUpdate()
    {
        publishJointState();
    }
}
