using System.Collections;
using System.Collections.Generic;
using UnityEngine;

public class PresetDomainRandomizer
{
    public enum PresetConfigurationLabels
    {
        C5L0,
        C5L1,
        C5L4,
        C5L7,
        C7L0,
        C10L0,
        C3L0,
        C3L4,
        C3L6,
        Experiment
    }

    [System.Serializable]
    public struct PresetConfigurationItem
    {
        public PresetConfigurationItem(string referenceName, float value)
        {
            this.referenceName = referenceName;
            this.value = value;
        }
        public string referenceName;
        public float value;
    }

    // Helper function to create simple camera/light preset configuration
    static public List<PresetConfigurationItem> CreateBasicPreset(Vector3 lightPos, Vector3 lightRot, Vector3 camPos, Vector3 camRot)
    {
        return new List<PresetConfigurationItem>()
        {
            new PresetConfigurationItem("light_px", lightPos.x),
            new PresetConfigurationItem("light_py", lightPos.y),
            new PresetConfigurationItem("light_pz", lightPos.z),

            new PresetConfigurationItem("light_rx", lightRot.x),
            new PresetConfigurationItem("light_ry", lightRot.y),
            new PresetConfigurationItem("light_rz", lightRot.z),

            new PresetConfigurationItem("camera_px", camPos.x),
            new PresetConfigurationItem("camera_py", camPos.y),
            new PresetConfigurationItem("camera_pz", camPos.z),

            new PresetConfigurationItem("camera_rx", camRot.x),
            new PresetConfigurationItem("camera_ry", camRot.y),
            new PresetConfigurationItem("camera_rz", camRot.z),
        };
    }

    [System.Serializable]
    public struct PresetConfiguration
    {
        public PresetConfiguration(PresetConfigurationLabels label, List<PresetConfigurationItem> presetItems)
        {
            this.label = label;
            this.presetItems = presetItems;
        }
        public PresetConfigurationLabels label;
        public List<PresetConfigurationItem> presetItems;
    }
    static public List<PresetConfiguration> BasicPresets = new List<PresetConfiguration>
    {
        new PresetConfiguration(PresetConfigurationLabels.C5L0, CreateBasicPreset(new Vector3(0f, 5f, 0f), new Vector3(90f, 0f, 0f), new Vector3(0f, 5f, 0f), new Vector3(90f, 0f, 0f))),
        new PresetConfiguration(PresetConfigurationLabels.C5L1, CreateBasicPreset(new Vector3(-4f, 5f, 2f), new Vector3(30f, 90f, 90f), new Vector3(0f, 5f, 0f), new Vector3(90f, 0f, 0f))),
        new PresetConfiguration(PresetConfigurationLabels.C5L4, CreateBasicPreset(new Vector3(-4f, 5f, 0f), new Vector3(30f, 90f, 90f), new Vector3(0f, 5f, 0f), new Vector3(90f, 0f, 0f))),
        new PresetConfiguration(PresetConfigurationLabels.C5L7, CreateBasicPreset(new Vector3(-4f, 5f, -2f), new Vector3(30f, 90f, 90f), new Vector3(0f, 5f, 0f), new Vector3(90f, 0f, 0f))),
        new PresetConfiguration(PresetConfigurationLabels.C7L0, CreateBasicPreset(new Vector3(0f, 5f, 0f), new Vector3(90f, 0f, 0f), new Vector3(-0.2f, 5f, -0.8f), new Vector3(75f, 0f, 0f))),
        new PresetConfiguration(PresetConfigurationLabels.C10L0, CreateBasicPreset(new Vector3(0f, 5f, 0f), new Vector3(90f, 0f, 0f), new Vector3(-0.2f, 4.5f, -2.2f), new Vector3(60f, 0f, 0f))),
        new PresetConfiguration(PresetConfigurationLabels.C3L0, CreateBasicPreset(new Vector3(0f, 5f, 0f), new Vector3(90f, 0f, 0f), new Vector3(0.7f, 4.5f, 0.3f), new Vector3(80f, -90f, -90f))),
        new PresetConfiguration(PresetConfigurationLabels.C3L4, CreateBasicPreset(new Vector3(-4f, 5f, 0f), new Vector3(30f, 90f, 90f), new Vector3(0.7f, 4.5f, 0.3f), new Vector3(80f, -90f, -90f))),
        new PresetConfiguration(PresetConfigurationLabels.C3L6, CreateBasicPreset(new Vector3(4f, 5f, 0f), new Vector3(30f, -90f, -90f), new Vector3(0.7f, 4.5f, 0.3f), new Vector3(80f, -90f, -90f))),
        new PresetConfiguration(PresetConfigurationLabels.Experiment, CreateBasicPreset(new Vector3(4f, 5f, 0f), new Vector3(30f, -90f, -90f), new Vector3(0.7f, 4.5f, 0.3f), new Vector3(80f, -90f, -90f)))
    };
}
