using System.Collections;
using System.Collections.Generic;
using UnityEngine;

// Formats all cameras to render on the same display simultaneously
// This does not effect ML-Agents as the rect are changed to full screen
// before recording observation
public class MultiViewCamera : MonoBehaviour
{
    [Header("Note: If list is empty, will auto-detect")] 
    public List<Camera> SceneCameras;

    void Start()
    {
        // Automaticall find all cameras in the scene (except Main Camera)
        if (SceneCameras.Count == 0)
        {
            SceneCameras = new List<Camera>();
            Camera[] cameras = FindObjectsOfType<Camera>();
            foreach (Camera cam in cameras)
            {
                if (!cam.CompareTag("MainCamera"))
                {
                    SceneCameras.Add(cam);
                }
            }
        }

        int num_rows ;
        if (SceneCameras.Count < 3) num_rows = 1;
        else if (SceneCameras.Count < 9) num_rows = 2;
        else num_rows = 3;

        int num_cols = SceneCameras.Count / num_rows;
        int camera_i = 0;
        for (int i = 0; i < num_rows; i++)
        {
            for (int j = 0; j < num_cols; j++)
            {
                float x = j * (1f / num_cols);
                float y = i * (1f / num_rows);
                float w = 1f / num_cols;
                float h = 1f / num_rows;
                SceneCameras[camera_i].rect = new Rect(x, y, w, h);
                camera_i++;
            }
        }
    }
}
