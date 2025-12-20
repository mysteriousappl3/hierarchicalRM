using UnityEngine;

namespace Obi
{
    [AddComponentMenu("Physics/Obi/Obi Cloth Renderer", 903)]
    [RequireComponent(typeof(MeshRenderer))]
    [RequireComponent(typeof(MeshFilter))]
    [ExecuteInEditMode]
    public class ObiClothRenderer : ObiClothRendererBase, ObiActorRenderer<ObiClothRenderer>
    {

        public float radius = 0.25f;
        public float falloff = 1;
        public uint maxInfluences = 4;

        public ObiCloth cloth;
        public ObiSkinMap customSkinMap;

        public override ObiActor actor
        {
            get { return cloth; }
        }

        public override Material[] materials {
            get { return meshRenderer.sharedMaterials; }
        }

        private MeshRenderer meshRenderer;
        private MeshFilter meshFilter;

        public override ObiSkinMap skinMap
        {
            get
            {
                if (customSkinMap != null || cloth == null || cloth.clothBlueprintBase == null)
                    return customSkinMap;
                return cloth.clothBlueprintBase.defaultSkinmap;
            }
            set { customSkinMap = value; }
        }

        protected void Awake()
        {
            sourceRenderer = meshRenderer = GetComponent<MeshRenderer>();
            meshFilter = GetComponent<MeshFilter>();

            // In case there's no user-set cloth reference,
            // try to find one in the same object:
            if (cloth == null)
                cloth = GetComponent<ObiCloth>();
        }

        public void CleanupRenderer()
        {
            meshFilter.sharedMesh = sourceMesh;
        }

        public override bool ValidateRenderer()
        {
            if (meshFilter == null)
                meshFilter = GetComponent<MeshFilter>();

            // no shared mesh, no custom skinmap, use the blueprint's input mesh:
            if (meshFilter.sharedMesh == null && customSkinMap == null &&  actor.sharedBlueprint != null)
                meshFilter.sharedMesh = ((ObiClothBlueprint)actor.sharedBlueprint).inputMesh;

            // if there's a sharedMesh, store it.
            if (meshFilter.sharedMesh != null)
                sourceMesh = meshFilter.sharedMesh;

            // at runtime, set the sharedMesh to null since we will be doing our own rendering.
            if (Application.isPlaying)
                meshFilter.sharedMesh = null;

            return base.ValidateRenderer();
        }

        public void OnEnable()
        {
            ((ObiActorRenderer<ObiClothRenderer>)this).EnableRenderer();
        }

        public void OnDisable()
        {
            ((ObiActorRenderer<ObiClothRenderer>)this).DisableRenderer();
        }

        public void OnValidate()
        {
            ((ObiActorRenderer<ObiClothRenderer>)this).SetRendererDirty(Oni.RenderingSystemType.Cloth);
        }

        public override void Bind()
        {
            if (skinMap != null && cloth.clothBlueprintBase != null)
            {
                meshFilter = GetComponent<MeshFilter>();
                var blueprintTransform = transform.gameObject == cloth.gameObject ? Matrix4x4.TRS(Vector3.zero, cloth.clothBlueprintBase.rotation, cloth.clothBlueprintBase.scale) : Matrix4x4.identity;
                skinMap.MapParticlesToVertices(meshFilter.sharedMesh, cloth.clothBlueprintBase, transform.localToWorldMatrix * blueprintTransform, cloth.transform.worldToLocalMatrix, radius, falloff, maxInfluences);
                skinMap.checksum = cloth.clothBlueprintBase.checksum;
            }
        }

        RenderSystem<ObiClothRenderer> ObiRenderer<ObiClothRenderer>.CreateRenderSystem(ObiSolver solver)
        {
            switch (solver.backendType)
            {

#if (OBI_BURST && OBI_MATHEMATICS && OBI_COLLECTIONS)
                case ObiSolver.BackendType.Burst: return new BurstClothRenderSystem(solver);
#endif
                case ObiSolver.BackendType.Compute:
                default:

                    if (SystemInfo.supportsComputeShaders)
                        return new ComputeClothRenderSystem(solver);
                    return null;

            }
        }

    }
}