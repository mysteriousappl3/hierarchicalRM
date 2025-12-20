using System;
using System.IO;
using System.Collections.Generic;
using System.Linq;
using UnityEngine;
#if UNITY_EDITOR
using UnityEditor;
#endif
using UnityEngine.Rendering;

/// <summary>
/// Episode recorder for recording episodes and logging input, output, domain parameters,
/// and typical RL parameters (step, reward etc.). Includes an experiment mode for testing models
/// </summary>

public enum EpisodeRecorderType { Disable, Basic, Experiment};

[DefaultExecutionOrder(-51)]
public class EpisodeRecorder : MonoBehaviour
{
    // This is a singleton class that can be accessed from anywhere
    public static EpisodeRecorder Instance { get; private set; }
    private void Awake()
    {
        if (Instance != null && Instance != this)
        {
            Destroy(this);
        }
        else
        {
            Instance = this;
        }

        if (!Application.isEditor)
        {
            Destroy(this);
        }
    }

    public EpisodeRecorderType episodeRecorderType;

    public uint NumberOfEpisodeToCollect = 10;
    public string RootDirectory = "data/";
    public bool RecordImages = false;
    public int ImageWidth = 128;
    public int ImageHeight = 128;


    private int episodeCounter = 0;
    private Dictionary<int, string> episodeData = new Dictionary<int, string>();
    private string timestamp = DateTime.Now.ToString("mm-HH-dd-MM-yyyy");

    public string VariableName;
    public float ExperimentVariableMin;
    public float ExperimentVariableMax;
    public int ExperimentVariableSteps = 10;
    public float NumberOfEpisodesPerStep = 10;

    private float[] experimentValues;
    private int experimentValueIndex;
    private int experimentCountPerStep;

    void Start()
    {
        experimentValues = linspace(ExperimentVariableMin, ExperimentVariableMax, ExperimentVariableSteps);
        experimentValueIndex = 0;
        experimentCountPerStep = 0;
        episodeData[0] = "";
    }
    
    public int StartNewEpisode(int episode_id, GameObject parentScene)
    {
        int currentEpisodeCount = episodeCounter;

        switch (episodeRecorderType)
        {
            case EpisodeRecorderType.Disable:
                return -1;

            case EpisodeRecorderType.Experiment:
                // If we have already reached the total number of experiments,
                // then we avoid incrementing and just wait for one of the episodes to end
                if (experimentValueIndex == ExperimentVariableSteps) return -1;
                
                StartNewExperiment(currentEpisodeCount, parentScene);
                
                episodeCounter++;
                experimentCountPerStep++;
                if (experimentCountPerStep % NumberOfEpisodesPerStep == 0)
                {
                    experimentValueIndex++;
                    experimentCountPerStep = 0;
                }

                return currentEpisodeCount; // We record everything for an experiment under the 0 index string

            case EpisodeRecorderType.Basic:
                episodeCounter++;
                return currentEpisodeCount;
            default:
                return -1;
        }
    }

    public void RecordEndEpisode(int episode_id, float reward, GameObject parentScene)
    {
        if (episode_id == -1) return;

        switch (episodeRecorderType)
        {
            case EpisodeRecorderType.Disable:
                break;

            case EpisodeRecorderType.Experiment:
                episodeData[episode_id] += reward + "\n";
                if (experimentValueIndex == ExperimentVariableSteps) WriteExperimentToFile();
                break;

            case EpisodeRecorderType.Basic:
                string episodeLine = -1 + "," + episode_id + "," + "0" + "," + "0" + "," + "0" + "," + "0" + "," + reward + "\n";
                episodeData[episode_id] += episodeLine;
                WriteToFile(episode_id, parentScene);
                break;

            default:
                break;
        }

#if UNITY_EDITOR
        if (episodeRecorderType == EpisodeRecorderType.Basic && episode_id == NumberOfEpisodeToCollect)
        {
            EditorApplication.isPlaying = false;
        }
        else if (episodeRecorderType == EpisodeRecorderType.Experiment && experimentValueIndex == ExperimentVariableSteps)
        {
            EditorApplication.isPlaying = false;
        }
#endif
    }


    public void StartNewExperiment(int episode_id, GameObject parentScene)
    {
        float val = experimentValues[experimentValueIndex];
        episodeData[episode_id] = val + ",";
        switch (VariableName)
        {
            case "camera_px":
                Camera cam = parentScene.GetComponentInChildren<Camera>();
                Vector3 pos = cam.gameObject.transform.localPosition;
                pos.x = val;
                cam.gameObject.transform.localPosition = pos;
                break;
            case "camera_py":
                break;
            case "camera_pz":
                break;
            case "camera_rx":
                break;            
            case "camera_ry":
                break;
            case "camera_rz":
                break;

            default:
                Debug.LogError("The specific variable name does not match those implemented in EpisodeRecorder.cs");
#if UNITY_EDITOR
                EditorApplication.isPlaying = false;
#endif                
                break;
        }
    }

    public void RecordStep(int episode_id, int step, Vector3 positionSignal, Quaternion rotationAction, float jawSignal, float reward, Camera cam = null)
    {
        switch (episodeRecorderType)
        {
            case EpisodeRecorderType.Disable:
                break;

            case EpisodeRecorderType.Experiment:
                break;

            case EpisodeRecorderType.Basic:
                string line = step + "," + episode_id + "," + positionSignal.x + "," + positionSignal.y + "," + positionSignal.z + "," + jawSignal + "," + reward + "\n";
                episodeData[episode_id] += line;
                if (RecordImages && cam != null) SaveCameraObservation(episode_id, step, cam, ImageWidth, ImageHeight);
                break;

            default:
                break;
        }
    }

    public void WriteToFile(int episode_id, GameObject parentScene)
    {
        string savePath = RootDirectory + timestamp + "/" + "episode_" + episode_id.ToString();
        DirectoryInfo dirInfo = Directory.CreateDirectory(savePath);

        string data = "step,episode_id,positionSignal.x,positionSignal.y,positionSignal.z,jawSignal,reward \n" + episodeData[episode_id];
        File.WriteAllText(dirInfo.FullName + "/data.csv", data);
        Debug.Log("Episode: " + episode_id.ToString() + " data saved to: " + dirInfo.FullName);

        episodeData.Remove(episode_id);

        // Record all relevant Environment Parameters
        string envParams = "Parameter, Value\n";

        Camera sceneCam = parentScene.GetComponentInChildren<Camera>();
        envParams += ("camera_px, " + sceneCam.transform.localPosition.x + "\n");
        envParams += ("camera_py, " + sceneCam.transform.localPosition.y + "\n");
        envParams += ("camera_pz, " + sceneCam.transform.localPosition.z + "\n");

        envParams += ("camera_rx, " + sceneCam.transform.localRotation.eulerAngles.x + "\n");
        envParams += ("camera_ry, " + sceneCam.transform.localRotation.eulerAngles.y + "\n");
        envParams += ("camera_rz, " + sceneCam.transform.localRotation.eulerAngles.z + "\n");

        Light sceneLight = parentScene.GetComponentInChildren<Light>();
        envParams += ("light_px, " + sceneLight.transform.localPosition.x + "\n");
        envParams += ("light_px, " + sceneLight.transform.localPosition.y + "\n");
        envParams += ("light_px, " + sceneLight.transform.localPosition.z + "\n");

        File.WriteAllText(dirInfo.FullName + "/params.csv", envParams);
    }

    public void WriteExperimentToFile()
    {
        string savePath = RootDirectory + timestamp + "/";
        DirectoryInfo dirInfo = Directory.CreateDirectory(savePath);

        string data =  VariableName + ",reward\n"; 
        
        for (int i = 0; i < episodeCounter; i++)
        {
            data += episodeData[i];
        }

        File.WriteAllText(dirInfo.FullName + "/experiment.csv", data);
    }

    public void SaveCameraObservation(int episode_id, int step, Camera cam, int width, int height)
    {
        if (SystemInfo.graphicsDeviceType == GraphicsDeviceType.Null)
        {
            Debug.LogError("GraphicsDeviceType is Null. This will likely crash when trying to render.");
        }

        var oldRec = cam.rect;
        cam.rect = new Rect(0f, 0f, 1f, 1f);
        var depth = 24;
        var format = RenderTextureFormat.Default;
        var readWrite = RenderTextureReadWrite.Default;
        Texture2D texture2D = new Texture2D(width, height, TextureFormat.RGBA32, false);

        var tempRt =
            RenderTexture.GetTemporary(width, height, depth, format, readWrite);

        var prevActiveRt = RenderTexture.active;
        var prevCameraRt = cam.targetTexture;

        // render to offscreen texture (readonly from CPU side)
        RenderTexture.active = tempRt;
        cam.targetTexture = tempRt;

        cam.Render();

        texture2D.ReadPixels(new Rect(0, 0, texture2D.width, texture2D.height), 0, 0);

        string savePath = RootDirectory + timestamp + "/" + "episode_" + episode_id + "/images";
        DirectoryInfo dirInfo = Directory.CreateDirectory(savePath);

        byte[] compressed = texture2D.EncodeToPNG();
        File.WriteAllBytes(dirInfo.FullName + "/" + "step_" + step + ".png", compressed);


        cam.targetTexture = prevCameraRt;
        cam.rect = oldRec;
        RenderTexture.active = prevActiveRt;
        RenderTexture.ReleaseTemporary(tempRt);

        if (Application.isEditor)
        {
            // Edit Mode tests complain if we use Destroy()
            UnityEngine.Object.DestroyImmediate(texture2D);
        }
        else
        {
            UnityEngine.Object.Destroy(texture2D);
        }
    }

    public float[] linspace(float startval, float endval, int steps)
    {
        float interval = (endval / Mathf.Abs(endval)) * Mathf.Abs(endval - startval) / (steps - 1);
        return (from val in Enumerable.Range(0, steps)
                select startval + (val * interval)).ToArray();
    }
}

#if UNITY_EDITOR
[CustomEditor(typeof(EpisodeRecorder))]
public class EpisodeRecorderEditor : Editor
{
    SerializedProperty recorderType;
    SerializedProperty imageEnabled;
    SerializedProperty ImageWidth;
    SerializedProperty ImageHeight;
    SerializedProperty RootDirectory;
    SerializedProperty NumberOfEpisodesToCollect;
    SerializedProperty VariableName;
    SerializedProperty ExperimentVariableMin;
    SerializedProperty ExperimentVariableMax;
    SerializedProperty ExperimentVariableSteps;
    SerializedProperty NumberOfEpisodesPerStep;

    void OnEnable()
    {
        recorderType = serializedObject.FindProperty("episodeRecorderType");
        imageEnabled = serializedObject.FindProperty("RecordImages");
        ImageWidth = serializedObject.FindProperty("ImageWidth");
        ImageHeight = serializedObject.FindProperty("ImageHeight");
        RootDirectory = serializedObject.FindProperty("RootDirectory");
        NumberOfEpisodesToCollect = serializedObject.FindProperty("NumberOfEpisodeToCollect");
        VariableName = serializedObject.FindProperty("VariableName");
        ExperimentVariableMin = serializedObject.FindProperty("ExperimentVariableMin");
        ExperimentVariableMax = serializedObject.FindProperty("ExperimentVariableMax");
        ExperimentVariableSteps = serializedObject.FindProperty("ExperimentVariableSteps");
        NumberOfEpisodesPerStep = serializedObject.FindProperty("NumberOfEpisodesPerStep");
    }

    // OnInspector GUI
    public override void OnInspectorGUI()
    {
        serializedObject.Update();
        EditorGUILayout.PropertyField(recorderType);
        GUILayout.Space(10);

        switch (recorderType.intValue)
        {
            case (int)EpisodeRecorderType.Disable:
                GUILayout.Label("Disabled", EditorStyles.boldLabel);
                GUILayout.Space(5);
                break;
            case (int)EpisodeRecorderType.Basic:
                GUILayout.Label("Basic Episode Recorder", EditorStyles.boldLabel);
                GUILayout.Space(5);

                EditorGUILayout.PropertyField(NumberOfEpisodesToCollect);
                EditorGUILayout.PropertyField(RootDirectory);
                EditorGUILayout.PropertyField(imageEnabled);

                if (imageEnabled.boolValue)
                {
                    using (var cHorizontalScope = new GUILayout.HorizontalScope())
                    {
                        GUILayout.Space(20f);

                        using (var cVerticalScope = new GUILayout.VerticalScope())
                        {
                            EditorGUILayout.PropertyField(ImageWidth);
                            EditorGUILayout.PropertyField(ImageHeight);
                        }
                    }
                }
                break;
            case (int)EpisodeRecorderType.Experiment:
                GUILayout.Label("Experiment Recorder", EditorStyles.boldLabel);
                GUILayout.Space(5);

                EditorGUILayout.PropertyField(RootDirectory);
                EditorGUILayout.PropertyField(VariableName);
                EditorGUILayout.PropertyField(ExperimentVariableMin);
                EditorGUILayout.PropertyField(ExperimentVariableMax);
                EditorGUILayout.PropertyField(ExperimentVariableSteps);
                EditorGUILayout.PropertyField(NumberOfEpisodesPerStep);
                break;
            default:
                break;
        }

        serializedObject.ApplyModifiedProperties();
    }
}
#endif
