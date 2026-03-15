using System;
using UnityEngine;
using UnityEngine.Serialization;
using Unity.MLAgents.Sensors;

[AddComponentMenu("RGBD Sensor")]
public class RGBDCameraSensorComponent : SensorComponent, IDisposable
{
    RGBDCameraSensor m_Sensor;

    public Camera Camera;
    public string SensorName = "RGBDCameraSensor";
    public int Width = 128;
    public int Height = 128;
    public ObservationType ObservationType;
    public bool RuntimeCameraEnable = true;

    [Range(1, 50)]
    public int ObservationStacks = 1;
    public SensorCompressionType Compression = SensorCompressionType.PNG;

    void Start()
    {
        UpdateSensor();
    }

    public override ISensor[] CreateSensors()
    {
        Dispose();
        m_Sensor = new RGBDCameraSensor(Camera, Width, Height, false, SensorName, Compression, ObservationType);

        if (ObservationStacks != 1)
        {
            return new ISensor[] { new StackingSensor(m_Sensor, ObservationStacks) };
        }
        return new ISensor[] { m_Sensor };
    }

    internal void UpdateSensor()
    {
        if (m_Sensor != null)
        {
            m_Sensor.Camera = Camera;
            m_Sensor.CompressionType = Compression;
            m_Sensor.Camera.enabled = RuntimeCameraEnable;
        }
    }

    public void Dispose()
    {
        if (!ReferenceEquals(m_Sensor, null))
        {
            m_Sensor.Dispose();
            m_Sensor = null;
        }
    }
}

