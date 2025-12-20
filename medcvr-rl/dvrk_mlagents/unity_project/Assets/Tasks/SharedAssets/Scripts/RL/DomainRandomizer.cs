using System.IO;
using UnityEngine;
#if UNITY_EDITOR
using UnityEditor;
#endif
using Unity.MLAgents;
using System.Collections.Generic;
using YamlDotNet.RepresentationModel;


/// <summary>
/// This Domain Randomizer script is built to override the ML-Agents domain
/// randomization feature with a custom implementation.
/// This allows more control over domain randomization to:
///     -Run tests to find failed domains
///     - Sample differently during training from default ML-Agents behaviour
///     - Use preset domains and test success rate
/// 
/// The original ML-Agents domain randomization through config files is still accessible!
/// Setting randomization type to 'ML-Agents' will revert to the original randomization.
/// 
/// This domain randomizer will be a singleton that can be globally accessed
/// using DomainRandomizer.Instance.Add the DomainRandomizer script to any
/// object in the scene to enable.
/// 
/// Usage: 
/// DomainRandomizer.instance.RandomizeDomain(
/// </summary>
public enum DomainRandomizationType { MLAgents, UniformSampler, Presets};


[System.Serializable]
public struct DomainRandomizerItem
{

    public string name;
    public string referenceName;
    public float min;
    public float max;

    public DomainRandomizerItem(string name, string referenceName, float min, float max)
    {
        this.name = name;
        this.referenceName = referenceName;
        this.min = min;
        this.max = max;
    }
}

// Main Domain Randomizer Class (See the next class for Custom Editor UI)
// Awake before Agent scripts due to early initialization of agents (order=50)
[DefaultExecutionOrder(-51)]
public class DomainRandomizer : MonoBehaviour
{
    // This is a singleton class that can be accessed from anywhere
    public static DomainRandomizer Instance { get; private set; }
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
    }

    private System.Random rand = new System.Random();
    public DomainRandomizationType RandomizationType;

    public bool UseConfigFile;
    public string PathToConfig;
    public bool UseCurriculum;
    public string LessonName;
    private YamlMappingNode yamlEnvParams;

    public PresetDomainRandomizer.PresetConfigurationLabels CurrentPreset;

    [SerializeField]
    public List<PresetDomainRandomizer.PresetConfiguration> ConfigurationPresets = PresetDomainRandomizer.BasicPresets;

    [SerializeField]
    public List<DomainRandomizerItem> baseRandomizations = new List<DomainRandomizerItem>()
    {
        new DomainRandomizerItem("Camera X Position", "camera_px", -0.05f, 0.05f),
        new DomainRandomizerItem("Camera Y Position", "camera_py", 2.15f, 2.25f),
        new DomainRandomizerItem("Camera Z Position", "camera_pz", 0.1f, 0.2f),

        new DomainRandomizerItem("Camera X Rotation", "camera_rx", 43f, 47f),
        new DomainRandomizerItem("Camera Y Rotation", "camera_ry", -1.5f, 1.5f),
        new DomainRandomizerItem("Camera Z Rotation", "camera_rz", -1.5f, 1.5f),

        new DomainRandomizerItem("Light X Position", "light_px", -3f, 3f),
        new DomainRandomizerItem("Light Y Position", "light_py", 4f, 7f),
        new DomainRandomizerItem("Light Z Position", "light_pz", -2f, 1.5f),
        new DomainRandomizerItem("Light Intensity", "light_intensity", 10f, 30f),

        new DomainRandomizerItem("Ground Static Friction", "static_friction", 0.0f, 0.3f),
        new DomainRandomizerItem("Ground Dynamic Friction", "dynamic_friction", 0.0f, 0.3f),

        new DomainRandomizerItem("Ground R Color", "ground_r", 0.25f, 0.35f),
        new DomainRandomizerItem("Ground G Color", "ground_g", 0.65f, 0.75f),
        new DomainRandomizerItem("Ground B Color", "ground_b", 0.95f, 1f),
    };

    public List<DomainRandomizerItem> taskSpecificRandomizations = new List<DomainRandomizerItem>();
    private List<DomainRandomizerItem> fullRandomizationList = new List<DomainRandomizerItem>();
    public Dictionary<string, float> defaultValues = new Dictionary<string, float>();

    private void Start()
    {
        yamlEnvParams = null;
        if (RandomizationType == DomainRandomizationType.MLAgents && UseConfigFile)
        {
            if (File.Exists(PathToConfig))
            {
                string fileString = File.ReadAllText(PathToConfig);
                var input = new StringReader(fileString);
                var yaml = new YamlStream();
                yaml.Load(input);
                var mapping = (YamlMappingNode)yaml.Documents[0].RootNode;

                try
                {
                    yamlEnvParams = (YamlMappingNode)mapping.Children[new YamlScalarNode("environment_parameters")];
                }
                catch
                {
                    Debug.LogWarning("Domain Randomizer: The config file does not have any environment_parameters");
                }
            }
            else
            {
                Debug.LogWarning("Domain Randomizer: The yaml file provided does not exist: " + PathToConfig);
            }
        }

        fullRandomizationList.AddRange(baseRandomizations);
        fullRandomizationList.AddRange(taskSpecificRandomizations);
    }

    public float GetValueFromYamlNode(YamlMappingNode node)
    {
        float newValue;
        try
        {
            YamlMappingNode value = (YamlMappingNode)node.Children[new YamlScalarNode("value")];
            YamlMappingNode samplerParams = (YamlMappingNode)value.Children[new YamlScalarNode("sampler_parameters")];
            string min = ((YamlScalarNode)samplerParams.Children[new YamlScalarNode("min_value")]).Value;
            string max = ((YamlScalarNode)samplerParams.Children[new YamlScalarNode("max_value")]).Value;
            newValue = float.Parse(min) + (float)rand.NextDouble() * (float.Parse(max) - float.Parse(min));
        }
        catch
        {
            newValue = float.Parse(((YamlScalarNode)node.Children[new YamlScalarNode("value")]).Value);
        }
        return newValue;
    }

    public float GetValueFromSamplingYamlNode(YamlMappingNode node)
    {
        float newValue;
        try
        {
            YamlMappingNode samplerParams = (YamlMappingNode)node.Children[new YamlScalarNode("sampler_parameters")];
            string min = ((YamlScalarNode)samplerParams.Children[new YamlScalarNode("min_value")]).Value;
            string max = ((YamlScalarNode)samplerParams.Children[new YamlScalarNode("max_value")]).Value;
            newValue = float.Parse(min) + (float)rand.NextDouble() * (float.Parse(max) - float.Parse(min));
        }
        catch
        {
            newValue = float.Parse(((YamlScalarNode)node.Children[new YamlScalarNode("value")]).Value);
        }
        return newValue;
    }

    public float RandomizeDomain(float currentValue, string referenceName)
    {
        float newValue = currentValue;

        // Store the default value of this variable in a dictionary
        if (!defaultValues.ContainsKey(referenceName))
        {
            defaultValues.Add(referenceName, currentValue);
        }

        switch (RandomizationType)
        {
            case DomainRandomizationType.MLAgents:
                if (Academy.Instance.IsCommunicatorOn)
                {
                    newValue = Academy.Instance.EnvironmentParameters.GetWithDefault(referenceName, defaultValues[referenceName]);
                }
                else if (yamlEnvParams != null && yamlEnvParams.Children.ContainsKey(new YamlScalarNode(referenceName)))
                {
                    try
                    {
                        YamlMappingNode envParam = (YamlMappingNode)yamlEnvParams.Children[new YamlScalarNode(referenceName)];
                        YamlMappingNode samplerParams = new YamlMappingNode();

                        if (UseCurriculum)
                        {
                            var curriculum = (YamlSequenceNode)envParam.Children[new YamlScalarNode("curriculum")];
                            foreach (YamlMappingNode lesson in curriculum)
                            {
                                if(((YamlScalarNode)lesson.Children[new YamlScalarNode("name")]).Value == LessonName)
                                {
                                    newValue = GetValueFromYamlNode(lesson);
                                }
                            }
                        }
                        else
                        {
                            newValue = GetValueFromSamplingYamlNode(envParam);
                        }
                    }
                    catch
                    {
                        Debug.LogWarning("Domain Randomizer: Something went wrong while trying to access the config dictionairy for: " + referenceName);
                    }
                }
                break;
            case DomainRandomizationType.UniformSampler:
                DomainRandomizerItem item = fullRandomizationList.Find(x => x.referenceName == referenceName);
                if (!item.Equals(default(DomainRandomizerItem)))
                {
                    newValue = item.min + (float)rand.NextDouble() * (item.max - item.min);
                }
                else
                {
                    Debug.LogWarning("Domain Randomizer: " + referenceName + " could not be found in the randomizations, default value used.");
                    newValue = defaultValues[referenceName];
                }
                break;
            case DomainRandomizationType.Presets:
                PresetDomainRandomizer.PresetConfigurationItem presetItem = ConfigurationPresets.Find(x => x.label == CurrentPreset).presetItems.Find(x => x.referenceName == referenceName);
                if (!presetItem.Equals(default(PresetDomainRandomizer.PresetConfigurationItem)))
                {
                    newValue = presetItem.value;
                }
                else
                {
                    Debug.LogWarning("Domain Randomizer: " + referenceName + " could not be found in the preset, default value used.");
                    newValue = defaultValues[referenceName];
                }
                break;
            default:
                break;
        }
        return newValue;
    }

    // Helper Function for Position
    public Vector3 RandomizeVec3(
        Vector3 currentValue,
        string xReferenceName,
        string yReferenceName,
        string zReferenceName)
    {
        return new Vector3(
            RandomizeDomain(currentValue.x, xReferenceName),
            RandomizeDomain(currentValue.y, yReferenceName),
            RandomizeDomain(currentValue.z, zReferenceName));
    }

    public Color RandomizeColor(
        Color currentValue,
        string rReferenceName,
        string gReferenceName,
        string bReferenceName)
    {
        return new Color(
            RandomizeDomain(currentValue.r, rReferenceName),
            RandomizeDomain(currentValue.g, gReferenceName),
            RandomizeDomain(currentValue.b, bReferenceName));
    }

    public Color GetRandomColor()
    {
        return new Color(
            (float)rand.NextDouble(),
            (float)rand.NextDouble(),
            (float)rand.NextDouble());
    }

    public void ChangePreset(PresetDomainRandomizer.PresetConfigurationLabels preset)
    {
        CurrentPreset = preset;
    }

    public void IncrementPreset()
    {
        int inc = ((int)CurrentPreset + 1) % System.Enum.GetNames(typeof(PresetDomainRandomizer.PresetConfigurationLabels)).Length;
        CurrentPreset = (PresetDomainRandomizer.PresetConfigurationLabels)inc;
    }
}
#if UNITY_EDITOR
[CustomEditor(typeof(DomainRandomizer))]
public class DomainRandomizerEditor : Editor
{
    SerializedProperty randomizationType;
    SerializedProperty useConfig;
    SerializedProperty useCurriculum;
    SerializedProperty pathToConfig;
    SerializedProperty lessonName;
    SerializedProperty baseRandomizations;
    SerializedProperty taskSpecificRandomizations;
    SerializedProperty currentPreset;
    SerializedProperty configurationPresets;

    void OnEnable()
    {
        randomizationType = serializedObject.FindProperty("RandomizationType");
        useConfig = serializedObject.FindProperty("UseConfigFile");
        useCurriculum = serializedObject.FindProperty("UseCurriculum");
        pathToConfig = serializedObject.FindProperty("PathToConfig");
        lessonName = serializedObject.FindProperty("LessonName");
        baseRandomizations = serializedObject.FindProperty("baseRandomizations");
        taskSpecificRandomizations = serializedObject.FindProperty("taskSpecificRandomizations");
        currentPreset = serializedObject.FindProperty("CurrentPreset");
        configurationPresets = serializedObject.FindProperty("ConfigurationPresets");
    }
    // OnInspector GUI
    public override void OnInspectorGUI()
    {
        serializedObject.Update();
        EditorGUILayout.PropertyField(randomizationType);

        GUILayout.Space(10);

        switch (randomizationType.intValue)
        {
            case (int)DomainRandomizationType.MLAgents:
                GUILayout.Label("ML-Agents Randomization Options", EditorStyles.boldLabel);
                GUILayout.Space(5);
                EditorGUILayout.PropertyField(useConfig);
                EditorGUILayout.PropertyField(pathToConfig);
                EditorGUILayout.PropertyField(useCurriculum);
                if ((bool)useCurriculum.boolValue)
                {
                    EditorGUILayout.PropertyField(lessonName);
                }
                break;
            case (int)DomainRandomizationType.UniformSampler:
                GUILayout.Label("Uniform Sampler Randomization Options", EditorStyles.boldLabel);
                GUILayout.Space(5);
                EditorGUILayout.PropertyField(baseRandomizations);
                EditorGUILayout.PropertyField(taskSpecificRandomizations);
                break;
            case (int)DomainRandomizationType.Presets:
                GUILayout.Label("Preset Sampler Randomization Options", EditorStyles.boldLabel);
                GUILayout.Space(5);
                EditorGUILayout.PropertyField(currentPreset);
                EditorGUILayout.PropertyField(configurationPresets);
                break;
            default:
                break;
        }

        serializedObject.ApplyModifiedProperties();
    }
}
#endif