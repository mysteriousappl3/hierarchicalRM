using System.Collections;
using System.Collections.Generic;
using Obi;
using UnityEngine;
#if UNITY_EDITOR
using UnityEditor;
#endif
using Unity.VisualScripting;

public class GenerateRopeMesh : MonoBehaviour
{
    public int NumHorizontalRope = 6;
    public int NumVerticalRope = 6;

    public float RopeThickness = 0.02f;
    public float DistanceBetweenRope = 0.2f;

    public float RopeResolution = 0.25f;

    public ObiRopeBlueprint ropeBlueprint;
    public ObiTearableClothBlueprint clothBlueprint;
    public Material ropeMaterial;

    public void CreateMesh()
    {
        CreateRopeBlueprint();
        List<ObiRope> verticalRopes = new List<ObiRope>();
        List<ObiRope> horizontalRopes = new List<ObiRope>();

        for (int i = 0; i < NumHorizontalRope; ++i)
        {
            ObiRope rope = CreateRope("hrope");
            rope.transform.position = transform.position + -transform.forward * DistanceBetweenRope * i;
            horizontalRopes.Add(rope);
        }

        for (int i = 0; i < NumVerticalRope; ++i)
        {
            ObiRope rope = CreateRope("vrope");
            rope.transform.rotation = Quaternion.Euler(0, 90, 0);
            rope.transform.position = transform.position + Vector3.right * DistanceBetweenRope * i;
            verticalRopes.Add(rope);
        }

        // Stitch particles that are near each other within a certain distance
        ObiSolver solver = transform.parent.GetComponent<ObiSolver>();

        solver.UpdateBackend();

        for (int hropeIndex = 0; hropeIndex < NumHorizontalRope; hropeIndex++)
        {
            for (int vropeIndex = 0; vropeIndex < NumVerticalRope; vropeIndex++)
            {
                GameObject pinPoint = GameObject.CreatePrimitive(PrimitiveType.Sphere);
                pinPoint.name = "Sphere" + hropeIndex + vropeIndex;
                pinPoint.transform.parent = transform;
                pinPoint.transform.localScale = new Vector3(0.01f, 0.01f, 0.01f);

                pinPoint.transform.position = new Vector3(
                    transform.position.x + DistanceBetweenRope * vropeIndex,
                    transform.position.y,
                    transform.position.z + -DistanceBetweenRope * hropeIndex
                );

                ObiParticleAttachment.AttachmentType attachmentType = ObiParticleAttachment.AttachmentType.Dynamic;

                if (vropeIndex == 0 || vropeIndex == NumVerticalRope - 1)
                {
                    attachmentType = ObiParticleAttachment.AttachmentType.Static;
                }
                else
                {
                    Rigidbody rigidBody = pinPoint.AddComponent<Rigidbody>();
                    rigidBody.mass = 0.001f;
                    rigidBody.useGravity = false;
                    ObiCollider col = pinPoint.AddComponent<ObiCollider>();
                    col.Filter = ObiUtils.MakeFilter(ObiUtils.CollideWithNothing, 0);
                }
                
                ObiParticleAttachment pin = verticalRopes[vropeIndex].gameObject.AddComponent<ObiParticleAttachment>();
                pin.particleGroup = verticalRopes[vropeIndex].blueprint.groups[hropeIndex];
                pin.target = pinPoint.transform;
                pin.attachmentType = attachmentType;

                pin = horizontalRopes[hropeIndex].gameObject.AddComponent<ObiParticleAttachment>();
                pin.particleGroup = horizontalRopes[hropeIndex].blueprint.groups[vropeIndex];
                pin.target = pinPoint.transform;
                pin.attachmentType = attachmentType;
            }
        }
    }

    public void CreateRopeBlueprint()
    {
#if UNITY_EDITOR
        ropeBlueprint = ScriptableObject.CreateInstance<ObiRopeBlueprint>();
        ropeBlueprint.path.Clear();
        AssetDatabase.CreateAsset(ropeBlueprint, "Assets/Tasks/SharedAssets/Resources/MeshRopeSection.asset");
        AssetDatabase.SaveAssets();

        int ropeMask = 1 << 2;
        var ropeFilter = ObiUtils.MakeFilter(ropeMask, 1);

        // Blueprint parameters:
        ropeBlueprint.resolution = RopeResolution;
        ropeBlueprint.thickness = RopeThickness;
        ropeBlueprint.pooledParticles = 2;

        float ropeMass = 0.001f;

        Vector3 startPosition = new Vector3(0, 0, 0);
        Vector3 endPosition = new Vector3(DistanceBetweenRope * (NumHorizontalRope - 1), 0, 0);
        
        // Build the rope path:
        ropeBlueprint.path.AddControlPoint(startPosition, Vector3.left * 0.05f, Vector3.right * 0.05f, Vector3.up, ropeMass, ropeMass, 1, ropeFilter, Color.white, "0");


        // Add control points for the remaining rope
        for (int i = 0; i < NumHorizontalRope - 2; i++)
        {
            Vector3 position = startPosition + Vector3.right * DistanceBetweenRope * (i + 1);
            ropeBlueprint.path.AddControlPoint(position, Vector3.left * 0.05f, Vector3.right * 0.05f, Vector3.up, ropeMass, ropeMass, 1, ropeFilter, Color.white, (i + 1).ToString());
        }

        ropeBlueprint.path.AddControlPoint(endPosition, Vector3.left * 0.05f, Vector3.right * 0.05f, Vector3.up, ropeMass, ropeMass, 1, ropeFilter, Color.white, (NumHorizontalRope - 1).ToString());
        ropeBlueprint.path.FlushEvents();

        // Generate particles/constraints:
        ropeBlueprint.GenerateImmediate();
#endif
    }


    public ObiRope CreateRope(string name = "rope")
    {
        GameObject ropeObject = new GameObject(name, typeof(ObiRope), typeof(ObiRopeExtrudedRenderer));
        ropeObject.transform.parent = transform;

        ObiRopeExtrudedRenderer ropeRenderer = ropeObject.AddComponent<ObiRopeExtrudedRenderer>();

        // get component references:
        ObiRope rope = ropeObject.GetComponent<ObiRope>();
        ropeRenderer = ropeObject.GetComponent<ObiRopeExtrudedRenderer>();

        // load the default rope section:
        ropeRenderer.section = Resources.Load<ObiRopeSection>("DefaultRopeSection");

        // instantiate and set the blueprint:
        rope.ropeBlueprint = ropeBlueprint;
        rope.stretchingScale = 0.9f;
        rope.maxBending = 0f;
        rope.surfaceCollisions = true;

        // Renderer renderer = ropeObject.AddComponent<Renderer>();
        // renderer.material = ropeMaterial;
        MeshRenderer meshRenderer = ropeObject.GetComponent<MeshRenderer>();
        meshRenderer.material = ropeMaterial;
        return rope;
    }
}

#if UNITY_EDITOR
[CustomEditor(typeof(GenerateRopeMesh)), CanEditMultipleObjects]
public class GenerateRopeMeshEditor : Editor
{
    public override void OnInspectorGUI()
    {
        GenerateRopeMesh generateRopeMesh = (GenerateRopeMesh)target;
        generateRopeMesh.NumHorizontalRope = EditorGUILayout.IntField("Number of Horizontal Ropes", generateRopeMesh.NumHorizontalRope);
        generateRopeMesh.NumHorizontalRope = EditorGUILayout.IntField("Number of Vertical Ropes", generateRopeMesh.NumHorizontalRope);

        generateRopeMesh.RopeThickness = EditorGUILayout.FloatField("Rope Thickness", generateRopeMesh.RopeThickness);
        generateRopeMesh.DistanceBetweenRope = EditorGUILayout.FloatField("Distance Between Ropes", generateRopeMesh.DistanceBetweenRope);
        generateRopeMesh.RopeResolution = EditorGUILayout.FloatField("RopeResolution", generateRopeMesh.RopeResolution);

        generateRopeMesh.ropeMaterial = EditorGUILayout.ObjectField("Material", generateRopeMesh.ropeMaterial, typeof(Material), false) as Material;
 
        if(GUILayout.Button("Generate Mesh"))
        {
            generateRopeMesh.CreateMesh();
        }
    }
}
#endif