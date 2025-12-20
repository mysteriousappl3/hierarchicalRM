using UnityEditor;
using UnityEngine;

namespace Obi
{

    [CustomEditor(typeof(ObiTearableClothRenderer))]
    public class ObiTearableClothRendererEditor : Editor
    {
        [MenuItem("CONTEXT/ObiTearableClothRenderer/Bake mesh")]
        static void Bake(MenuCommand command)
        {
            ObiTearableClothRenderer renderer = (ObiTearableClothRenderer)command.context;

            if (renderer.actor.isLoaded)
            {
                var system = renderer.actor.solver.GetRenderSystem<ObiTearableClothRenderer>() as ObiClothRenderSystem;

                if (system != null)
                {
                    var mesh = new Mesh();
                    system.BakeMesh(renderer, ref mesh, true);
                    ObiEditorUtils.SaveMesh(mesh, "Save cloth mesh", "cloth mesh");
                    GameObject.DestroyImmediate(mesh);
                }
            }
        }


        public override void OnInspectorGUI()
        {
            serializedObject.UpdateIfRequiredOrScript();

            // Apply changes to the serializedProperty
            if (GUI.changed)
                serializedObject.ApplyModifiedProperties();

        }
    }

}

