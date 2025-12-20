using UnityEngine;
using System.IO;
using static System.Net.Mime.MediaTypeNames;
using System.Diagnostics;
using System.Collections;

public class SnipCameraScript : MonoBehaviour
{
    // Initialized in Scene

    public GameObject psm_lnd;
    public RenderTexture renderTexture;

    private string folderPath = Path.Combine(UnityEngine.Application.dataPath, "Tasks/PegTransferTask/Task_Images");
    private string figuresFolderPath = Path.Combine(UnityEngine.Application.dataPath, "Tasks/PegTransferTask/Task_Figures_Images");

    public int imageCounter = 0;

    private void Start()
    {

        // Check if the directory exists
        if (Directory.Exists(folderPath))
        {

            //// Clear content for task figures folder
            // Get all files in the directory
            string[] files = Directory.GetFiles(figuresFolderPath);
            foreach (string file in files)
            {
                try
                {
                    File.Delete(file); // Delete each file
                }
                catch (IOException e)
                {
                    UnityEngine.Debug.LogError($"Failed to delete file: {file}. Error: {e.Message}");
                }
            }

            // Get all files in the directory
            files = Directory.GetFiles(folderPath);
            foreach (string file in files)
            {
                try
                {
                    File.Delete(file); // Delete each file
                }
                catch (IOException e)
                {
                    UnityEngine.Debug.LogError($"Failed to delete file: {file}. Error: {e.Message}");
                }
            }

            // Optionally, delete subdirectories if any
            string[] subdirectories = Directory.GetDirectories(folderPath);
            foreach (string subdirectory in subdirectories)
            {
                try
                {
                    Directory.Delete(subdirectory, true); // Delete the subdirectory and its contents
                    UnityEngine.Debug.Log($"Deleted subdirectory: {subdirectory}");
                }
                catch (IOException e)
                {
                    UnityEngine.Debug.LogError($"Failed to delete subdirectory: {subdirectory}. Error: {e.Message}");
                }
            }

            UnityEngine.Debug.Log($"Directory contents cleared: {folderPath}");
        }
        else
        {
            UnityEngine.Debug.LogWarning($"Directory does not exist: {folderPath}");
        }
    }

    void Update()
    {
        // Check if the 'O' key is pressed
        if (Input.GetKeyDown(KeyCode.O))
        {
            SaveImage();
        }
    }

    void SetLayerRecursively(GameObject obj, int newLayer)
    {
        obj.layer = newLayer;
        foreach (Transform child in obj.transform)
        {
            // UnityEngine.Debug.Log(newLayer);
            SetLayerRecursively(child.gameObject, newLayer);
        }
    }
    public IEnumerator SaveImage(string fileName = "")
    {
        if (renderTexture == null)
        {
            UnityEngine.Debug.LogError("Render Texture is not assigned.");
            yield break;
        }

        // Increment the image counter
        imageCounter += 1;


        // Disable the ignore camera layer to allow robot arm to be seen in the camera render

        // 1. Remove IgnoreCamera layer
        SetLayerRecursively(psm_lnd, LayerMask.NameToLayer("Default"));   // <-- remove IgnoreCamera

        yield return null;
        // Activate the Render Texture
        RenderTexture currentRT = RenderTexture.active;
        RenderTexture.active = renderTexture;

        // Create a Texture2D to copy the Render Texture
        Texture2D image = new Texture2D(renderTexture.width, renderTexture.height, TextureFormat.RGB24, false);
        image.ReadPixels(new Rect(0, 0, renderTexture.width, renderTexture.height), 0, 0);
        image.Apply();

        // Reset the active Render Texture
        RenderTexture.active = currentRT;

        // Encode the Texture2D to PNG format
        byte[] bytes = image.EncodeToPNG();

        // Ensure the folder path exists
        if (!Directory.Exists(figuresFolderPath))
        {
            Directory.CreateDirectory(figuresFolderPath);
        }

        // Define the file path with unique naming
        string filePath;
        if (fileName != "")
        {
            filePath = Path.Combine(figuresFolderPath, fileName);
        }
        else
        {
            // TODO: Make it dynamic so that for start scene it's Image_Start and for final outerbot check its Image_End
            filePath = Path.Combine(figuresFolderPath, $"SceneImage_{imageCounter}.png");
            UnityEngine.Debug.Log("save image with name = " + $"SceneImage_{imageCounter}.png");
            //filePath = Path.Combine(figuresFolderPath, $"SceneImage.png");
        }

        File.WriteAllBytes(filePath, bytes);


        // Log the save location
        UnityEngine.Debug.Log($"Render Texture saved as image to: {filePath}");


        // 2. Reactivate and now take screenshot of scene
        SetLayerRecursively(psm_lnd, LayerMask.NameToLayer("IgnoreCamera"));   // <-- add it back
        yield return null;

        // Activate the Render Texture
        currentRT = RenderTexture.active;
        RenderTexture.active = renderTexture;

        // Create a Texture2D to copy the Render Texture
        image = new Texture2D(renderTexture.width, renderTexture.height, TextureFormat.RGB24, false);
        image.ReadPixels(new Rect(0, 0, renderTexture.width, renderTexture.height), 0, 0);
        image.Apply();

        // Reset the active Render Texture
        RenderTexture.active = currentRT;

        // Encode the Texture2D to PNG format
        bytes = image.EncodeToPNG();

        // Ensure the folder path exists
        if (!Directory.Exists(folderPath))
        {
            Directory.CreateDirectory(folderPath);
        }

        // Define the file path with unique naming
        filePath = "";
        if (fileName != "")
        {
            filePath = Path.Combine(folderPath, fileName);
        }
        else
        {
            // TODO: Make it dynamic so that for start scene it's Image_Start and for final outerbot check its Image_End
            filePath = Path.Combine(folderPath, $"SceneImage_{imageCounter}.png");
            UnityEngine.Debug.Log("save image with name = " + $"SceneImage_{imageCounter}.png");
            //filePath = Path.Combine(folderPath, $"SceneImage.png");
        }

        File.WriteAllBytes(filePath, bytes);


        // Log the save location
        UnityEngine.Debug.Log($"Render Texture saved as image to: {filePath}");
        yield break;
    }
}
