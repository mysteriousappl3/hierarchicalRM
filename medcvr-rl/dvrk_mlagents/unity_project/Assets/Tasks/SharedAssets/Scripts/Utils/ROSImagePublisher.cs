using System.Collections;
using System.Collections.Generic;
using Unity.Robotics.ROSTCPConnector;
using Unity.Robotics.ROSTCPConnector.MessageGeneration;
using RosMessageTypes.Sensor;
using UnityEngine;

public class ROSImagePublisher : MonoBehaviour
{
    public Camera Camera;
    public string TopicName = "unity/image_raw";

    public int Height = 64;
    public int Width = 64;

    public int SkipFrames = 0;

    private int counter = 0;

    private Texture2D tex;

    private ROSConnection rosNode;
    void Start()
    {
        rosNode = ROSConnection.GetOrCreateInstance();
        rosNode.RegisterPublisher<ImageMsg>(TopicName);
        tex = new Texture2D(Width, Height, TextureFormat.RGB24, false);
    }

    // Update is called once per frame
    void FixedUpdate()
    {
        if (counter > SkipFrames)
        {
            StartCoroutine(SendImage()); 
            counter = 0;
        }
        counter ++;
    }

    public IEnumerator SendImage()
    {
        yield return new WaitForEndOfFrame();

        var oldRec = Camera.rect;
        Camera.rect = new Rect(0f, 0f, 1f, 1f);
        var depth = 24;
        var format = RenderTextureFormat.Default;
        var readWrite = RenderTextureReadWrite.Default;

        var tempRt =
            RenderTexture.GetTemporary(Width, Height, depth, format, readWrite);

        var prevActiveRt = RenderTexture.active;
        var prevCameraRt = Camera.targetTexture;

        // render to offscreen texture (readonly from CPU side)
        RenderTexture.active = tempRt;
        Camera.targetTexture = tempRt;

        Camera.Render();

        tex.ReadPixels(new Rect(0, 0, tex.width, tex.height), 0, 0);
        
        Camera.targetTexture = prevCameraRt;
        Camera.rect = oldRec;
        RenderTexture.active = prevActiveRt;
        RenderTexture.ReleaseTemporary(tempRt);

        // Encode the texture as an ImageMsg, and send to ROS

        ImageMsg imageMsg = MessageExtensions.ToImageMsg(tex, new RosMessageTypes.Std.HeaderMsg());
        imageMsg.step = 3 * (uint)tex.width;
        rosNode.Publish(TopicName, imageMsg);
    }
}
