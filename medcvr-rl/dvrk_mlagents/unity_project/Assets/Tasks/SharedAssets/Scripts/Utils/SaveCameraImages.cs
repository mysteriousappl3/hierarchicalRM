using System.Collections;
using System.Collections.Generic;
using UnityEngine;

public class SaveCameraImages : MonoBehaviour
{

    public string folderName = "Data";
    public float fps = 1.0f;

    private int fileCounter = 0;
    private float prevTime = 0.0f;

    // Update is called once per frame
    void Update()
    {
        if (Time.time - prevTime > 1.0f / fps)
        {
            prevTime = Time.time;
            CaptureScreenshot();
            fileCounter++;
        }
    }

    void CaptureScreenshot()
    {
        System.IO.Directory.CreateDirectory(folderName);
        Debug.Log(fileCounter);
        ScreenCapture.CaptureScreenshot(folderName + "/" + fileCounter + ".png");
        fileCounter++;
    }
}
