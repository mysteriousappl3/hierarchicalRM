using UnityEditor;
using UnityEngine;

namespace Obi
{

    [CustomEditor(typeof(ObiClothRenderer))]
    public class ObiClothRendererEditor : Editor
    {
        ObiClothRenderer clothRenderer;

        SerializedProperty cloth;

        SerializedProperty skinMap;
        SerializedProperty radius;
        SerializedProperty falloff;
        SerializedProperty maxInfluences;

        [MenuItem("CONTEXT/ObiClothRenderer/Bake mesh")]
        static void Bake(MenuCommand command)
        {
            ObiClothRenderer renderer = (ObiClothRenderer)command.context;

            if (renderer.actor.isLoaded)
            {
                var system = renderer.actor.solver.GetRenderSystem<ObiClothRenderer>() as ObiClothRenderSystem;

                if (system != null)
                {
                    var mesh = new Mesh();
                    system.BakeMesh(renderer, ref mesh, true);
                    ObiEditorUtils.SaveMesh(mesh, "Save cloth mesh", "cloth mesh");
                    GameObject.DestroyImmediate(mesh);
                }
            }
        }

        public void OnEnable()
        {
            clothRenderer = (ObiClothRenderer)target;
            cloth = serializedObject.FindProperty("cloth");

            skinMap = serializedObject.FindProperty("customSkinMap");
            radius = serializedObject.FindProperty("radius");
            falloff = serializedObject.FindProperty("falloff");
            maxInfluences = serializedObject.FindProperty("maxInfluences");
        }

        public override void OnInspectorGUI()
        {
            serializedObject.UpdateIfRequiredOrScript();

            EditorGUILayout.PropertyField(cloth);

            GUI.enabled = !Application.isPlaying;

            GUILayout.BeginHorizontal();
            EditorGUILayout.PropertyField(skinMap);

            if (clothRenderer.customSkinMap == null)
            {
                if (GUILayout.Button("Create", EditorStyles.miniButton, GUILayout.MaxWidth(80)))
                {
                    string path = EditorUtility.SaveFilePanel("Save skinmap", "Assets/", "ClothSkinmap", "asset");
                    if (!string.IsNullOrEmpty(path))
                    {
                        path = FileUtil.GetProjectRelativePath(path);
                        ObiSkinMap asset = ScriptableObject.CreateInstance<ObiSkinMap>();

                        AssetDatabase.CreateAsset(asset, path);
                        AssetDatabase.SaveAssets();

                        clothRenderer.skinMap = asset;
                    }
                }
            }
            GUILayout.EndHorizontal();

            if (clothRenderer.customSkinMap != null)
            {
                EditorGUI.indentLevel++;
                EditorGUILayout.PropertyField(radius);
                EditorGUILayout.PropertyField(falloff);

                if (maxInfluences != null) // tearable cloth doesn't have maxInfluences since it's always 1.
                    EditorGUILayout.PropertyField(maxInfluences);

                var color = GUI.color;
                if (!Application.isPlaying)
                {
                    if (!clothRenderer.ValidateRenderer())
                        GUI.color = Color.red;
                }

                if (GUILayout.Button("Bind"))
                {
                    clothRenderer.Bind();
                    EditorUtility.SetDirty(clothRenderer.skinMap);
                    AssetDatabase.SaveAssets();
                }
                GUI.color = color;
                EditorGUI.indentLevel--;
            }

            GUI.enabled = true;

            // Apply changes to the serializedProperty
            if (GUI.changed)
                serializedObject.ApplyModifiedProperties();

        }
    }

}

