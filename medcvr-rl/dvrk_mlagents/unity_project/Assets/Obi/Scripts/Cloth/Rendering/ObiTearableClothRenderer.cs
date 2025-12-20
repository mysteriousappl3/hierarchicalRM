using UnityEngine;
using System.Collections.Generic;
using System;

namespace Obi
{
    [AddComponentMenu("Physics/Obi/Obi Tearable Cloth Renderer", 904)]
    [RequireComponent(typeof(MeshRenderer))]
    [RequireComponent(typeof(MeshFilter))]
    [RequireComponent(typeof(ObiTearableCloth))]
    [ExecuteInEditMode]
    public class ObiTearableClothRenderer : ObiClothRendererBase, ObiActorRenderer<ObiTearableClothRenderer>
    {
        public float radius = 0.25f;
        public float falloff = 1;
        private ObiTearableCloth cloth;

        private HashSet<int> meshVertices = new HashSet<int>();
        private ObiSkinMap m_SkinmapInstance;

        protected List<Vector3> clothVertices = new List<Vector3>();
        protected List<Vector3> clothNormals = new List<Vector3>();
        protected List<Vector4> clothTangents = new List<Vector4>();
        protected List<Color> clothColors = new List<Color>();
        protected List<Vector2> clothTexCoord0 = new List<Vector2>();
        protected List<Vector2> clothTexCoord1 = new List<Vector2>();
        protected List<Vector2> clothTexCoord2 = new List<Vector2>();
        protected List<Vector2> clothTexCoord3 = new List<Vector2>();
        protected List<int> clothTriangles = new List<int>();

        public override ObiActor actor
        {
            get { return cloth; }
        }

        public override Material[] materials
        {
            get { return meshRenderer.sharedMaterials; }
        }

        public override int vertexCount { get { return clothVertices.Count; } }
        public override int triangleCount { get { return clothTriangles.Count / 3; } }

        private MeshRenderer meshRenderer;
        private MeshFilter meshFilter;

        [SerializeField][HideInInspector]
        private Mesh sharedMesh;

        public override ObiMesh topology
        {
            // Get a unique copy of the blueprint, since we'll be adding clusters to its topology when tearing.
            get { return cloth != null ? ((ObiTearableClothBlueprint)cloth.blueprint).topology : null; }
        }

        public override ObiSkinMap skinMap
        {
            get
            {
                if (m_SkinmapInstance != null)
                    return m_SkinmapInstance;

                return cloth.clothBlueprintBase.defaultSkinmap;
            }
            set { }
        }

        protected void Awake()
        {
            sourceRenderer = meshRenderer = GetComponent<MeshRenderer>();
            meshFilter = GetComponent<MeshFilter>();

            // In case there's no user-set cloth reference,
            // try to find one in the same object:
            cloth = GetComponent<ObiTearableCloth>();

            // need to update the mesh during tearing even if the renderer is disabled,
            // so subscribe to the tearing event here in Awake() instead of OnEnable().
            if (cloth != null)
                cloth.OnClothTorn += UpdateTornMeshVertices;
        }

        protected void OnDestroy()
        {
            if (cloth != null)
                cloth.OnClothTorn -= UpdateTornMeshVertices;
        }

        protected void DestroyMeshAndSkinmapInstances()
        {
            if (Application.isPlaying)
            {
                Destroy(m_SkinmapInstance); 
                Destroy(sourceMesh);

                m_SkinmapInstance = null;
                sourceMesh = null;
            }
        }

        protected void InstantiateMeshAndSkinmap()
        {
            if (Application.isPlaying && sourceMesh != null && m_SkinmapInstance == null)
            {
                // Create unique instance of the skinmap:
                m_SkinmapInstance = Instantiate(skinMap);

                // Create a unique instance of the mesh, and retrieve its data:
                sharedMesh = sourceMesh;
                sourceMesh = Instantiate(sourceMesh);
                GetClothMeshData();
            }
        }

        public void CleanupRenderer()
        {
            DestroyMeshAndSkinmapInstances();
            meshFilter.sharedMesh = sharedMesh;
        }

        public override bool ValidateRenderer()
        {
            if (meshFilter == null)
                meshFilter = GetComponent<MeshFilter>();

            // no shared mesh, no custom skinmap, use the blueprint's input mesh:
            if (meshFilter.sharedMesh == null && actor.sharedBlueprint != null)
                meshFilter.sharedMesh = ((ObiClothBlueprint)actor.sharedBlueprint).inputMesh;

            // if there's a sharedMesh, store it.
            if (meshFilter.sharedMesh != null)
                sourceMesh = meshFilter.sharedMesh;

            // Instantiate mesh/skinmap if necessary, that is only if we don't have a skinmap instance already.
            InstantiateMeshAndSkinmap();

            if (Application.isPlaying)
                meshFilter.sharedMesh = null;

            return base.ValidateRenderer();
        }

        public void OnEnable()
        {
            ((ObiActorRenderer<ObiTearableClothRenderer>)this).EnableRenderer();
        }

        public void OnDisable()
        {
            ((ObiActorRenderer<ObiTearableClothRenderer>)this).DisableRenderer();
        }

        public override void Bind()
        {
            if (skinMap != null && cloth.clothBlueprintBase != null)
            {
                meshFilter = GetComponent<MeshFilter>();
                var blueprintTransform = transform.gameObject == cloth.gameObject ? Matrix4x4.TRS(Vector3.zero, cloth.clothBlueprintBase.rotation, cloth.clothBlueprintBase.scale) : Matrix4x4.identity;
                skinMap.MapParticlesToVertices(meshFilter.sharedMesh, cloth.clothBlueprintBase, cloth.transform.localToWorldMatrix * blueprintTransform, cloth.transform.worldToLocalMatrix, radius, falloff, 1);
                skinMap.checksum = cloth.clothBlueprintBase.checksum;
            }
        }

        private void GetClothMeshData()
        {
            if (sourceMesh != null)
            {
                sourceMesh.GetVertices(clothVertices);
                sourceMesh.GetNormals(clothNormals);
                sourceMesh.GetTangents(clothTangents);
                sourceMesh.GetColors(clothColors);

                sourceMesh.GetUVs(0, clothTexCoord0);
                sourceMesh.GetUVs(1, clothTexCoord1);
                sourceMesh.GetUVs(2, clothTexCoord2);
                sourceMesh.GetUVs(3, clothTexCoord3);

                sourceMesh.GetTriangles(clothTriangles, 0);
            }
        }

        private void UpdateTornMeshVertices(object sender, ObiTearableCloth.ObiClothTornEventArgs args)
        {
            meshVertices.Clear();

            // copy bind pose:
            m_SkinmapInstance.bindPoses[topology.clusters.Count - 1] = m_SkinmapInstance.bindPoses[args.particleIndex];

            foreach (var face in args.updatedFaces)
            {
                int triIndex = face.index * 3;
                int v1 = clothTriangles[triIndex];
                int v2 = clothTriangles[triIndex + 1];
                int v3 = clothTriangles[triIndex + 2];

                if (m_SkinmapInstance.particlesOnVertices.influences[v1].index == args.particleIndex)
                    meshVertices.Add(v1);
                else if (m_SkinmapInstance.particlesOnVertices.influences[v2].index == args.particleIndex)
                    meshVertices.Add(v2);
                else if (m_SkinmapInstance.particlesOnVertices.influences[v3].index == args.particleIndex)
                    meshVertices.Add(v3);
            }

            foreach (int j in meshVertices)
            {
                if (j < clothVertices.Count) clothVertices.Add(clothVertices[j]);
                if (j < clothNormals.Count) clothNormals.Add(clothNormals[j]);
                if (j < clothTangents.Count) clothTangents.Add(clothTangents[j]);
                if (j < clothColors.Count) clothColors.Add(clothColors[j]);
                if (j < clothTexCoord0.Count) clothTexCoord0.Add(clothTexCoord0[j]);
                if (j < clothTexCoord1.Count) clothTexCoord1.Add(clothTexCoord1[j]);
                if (j < clothTexCoord2.Count) clothTexCoord2.Add(clothTexCoord2[j]);
                if (j < clothTexCoord3.Count) clothTexCoord3.Add(clothTexCoord3[j]);

                // map the new mesh vertex to the last topology vertex (the one we just created):
                m_SkinmapInstance.particlesOnVertices.influences.Add(new ObiInfluenceMap.Influence(topology.clusters.Count - 1, 1));

                int lastOffset = m_SkinmapInstance.particlesOnVertices.influenceOffsets[m_SkinmapInstance.particlesOnVertices.influenceOffsets.count - 1];
                m_SkinmapInstance.particlesOnVertices.influenceOffsets.Add(lastOffset + 1);

                // re-wire mesh triangles, so that they reference the new mesh vertices:
                foreach (var face in args.updatedFaces)
                {
                    int triIndex = face.index * 3;
                    if (clothTriangles[triIndex] == j) clothTriangles[triIndex] = clothVertices.Count - 1;
                    if (clothTriangles[triIndex + 1] == j) clothTriangles[triIndex + 1] = clothVertices.Count - 1;
                    if (clothTriangles[triIndex + 2] == j) clothTriangles[triIndex + 2] = clothVertices.Count - 1;
                }
            }

            cloth.SetRenderingDirty(Oni.RenderingSystemType.TearableCloth);
        }

        public override void GetVertices(List<Vector3> vertices) { vertices.Clear(); vertices.AddRange(clothVertices); }
        public override void GetNormals(List<Vector3> normals) { normals.Clear(); normals.AddRange(clothNormals); }
        public override void GetTangents(List<Vector4> tangents) { tangents.Clear(); tangents.AddRange(clothTangents); }
        public override void GetColors(List<Color> colors) { colors.Clear(); colors.AddRange(clothColors); }
        public override void GetUVs(int channel, List<Vector2> uvs)
        {
            uvs.Clear();
            switch (channel)
            {
                case 0: uvs.AddRange(clothTexCoord0); break;
                case 1: uvs.AddRange(clothTexCoord1); break;
                case 2: uvs.AddRange(clothTexCoord2); break;
                case 3: uvs.AddRange(clothTexCoord3); break;
            }
        }

        public override void GetTriangles(List<int> triangles) { triangles.Clear(); triangles.AddRange(clothTriangles); }

        RenderSystem<ObiTearableClothRenderer> ObiRenderer<ObiTearableClothRenderer>.CreateRenderSystem(ObiSolver solver)
        {
            switch (solver.backendType)
            {

#if (OBI_BURST && OBI_MATHEMATICS && OBI_COLLECTIONS)
                case ObiSolver.BackendType.Burst: return new BurstTearableClothRenderSystem(solver);
#endif
                case ObiSolver.BackendType.Compute:
                default:

                    if (SystemInfo.supportsComputeShaders)
                        return new ComputeTearableClothRenderSystem(solver);
                    return null;
            }
        }
    }
}