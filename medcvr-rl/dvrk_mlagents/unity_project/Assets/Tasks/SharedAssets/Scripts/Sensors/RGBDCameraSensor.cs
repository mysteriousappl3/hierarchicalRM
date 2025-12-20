using System;
using System.IO;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Experimental.Rendering;
using Unity.MLAgents.Sensors;

/// <summary>
/// Extension of standard Camera Sensor for RGB-D images with depth in the fourth channel.
/// </summary>
public class RGBDCameraSensor : ISensor, IDisposable
{
    Camera m_Camera;
    int m_Width;
    int m_Height;
    bool m_Grayscale;
    string m_Name;
    private ObservationSpec m_ObservationSpec;
    SensorCompressionType m_CompressionType;
    Texture2D m_Texture;

    public Camera Camera
    {
        get { return m_Camera; }
        set { m_Camera = value; }
    }

    public SensorCompressionType CompressionType
    {
        get { return m_CompressionType; }
        set { m_CompressionType = value; }
    }

    public RGBDCameraSensor(
        Camera camera, int width, int height, bool grayscale, string name, SensorCompressionType compression, ObservationType observationType = ObservationType.Default)
    {
        m_Camera = camera;
        m_Width = width;
        m_Height = height;
        m_Grayscale = grayscale;
        m_Name = name;
        var channels = grayscale ? 1 : 4; // RGBD
        m_ObservationSpec = ObservationSpec.Visual(channels, height, width, observationType);
        m_CompressionType = compression;
        m_Texture = new Texture2D(width, height, TextureFormat.RGBA32, false);
    }

    public string GetName()
    {
        return m_Name;
    }

    public ObservationSpec GetObservationSpec()
    {
        return m_ObservationSpec;
    }

    public byte[] GetCompressedObservation()
    {
        ObservationToTexture(m_Camera, m_Texture, m_Width, m_Height);
        var compressed = m_Texture.EncodeToPNG();
        return compressed;
    }

    public int Write(ObservationWriter writer)
    {
        ObservationToTexture(m_Camera, m_Texture, m_Width, m_Height);
        var numWritten = writer.WriteTexture(m_Texture, m_Grayscale);
        return numWritten;
    }

    public void Update() { }

    public void Reset() { }

    public CompressionSpec GetCompressionSpec()
    {
        return new CompressionSpec(m_CompressionType);
    }

    public static void ObservationToTexture(Camera obsCamera, Texture2D texture2D, int width, int height)
    {
        if (SystemInfo.graphicsDeviceType == GraphicsDeviceType.Null)
        {
            Debug.LogError("GraphicsDeviceType is Null. This will likely crash when trying to render.");
        }

        var oldRec = obsCamera.rect;
        obsCamera.rect = new Rect(0f, 0f, 1f, 1f);
        var depth = 32;

        var readWrite = RenderTextureReadWrite.Default;

        var tempRt =
            RenderTexture.GetTemporary(width, height, depth, RenderTextureFormat.ARGB32, readWrite);
        tempRt.filterMode = FilterMode.Point;

        var prevActiveRt = RenderTexture.active;
        var prevCameraRt = obsCamera.targetTexture;

        // render to offscreen texture (readonly from CPU side)
        RenderTexture.active = tempRt;
        obsCamera.targetTexture = tempRt;

        obsCamera.Render();

        texture2D.ReadPixels(new Rect(0, 0, texture2D.width, texture2D.height), 0, 0);

        obsCamera.targetTexture = prevCameraRt;
        obsCamera.rect = oldRec;
        RenderTexture.active = prevActiveRt;
        RenderTexture.ReleaseTemporary(tempRt);
    }

    public void Dispose()
    {
        if (!ReferenceEquals(null, m_Texture))
        {
            if (Application.isEditor)
            {
                // Edit Mode tests complain if we use Destroy()
                UnityEngine.Object.DestroyImmediate(m_Texture);
            }
            else
            {
                UnityEngine.Object.Destroy(m_Texture);
            }
            m_Texture = null;
        }
    }
}
