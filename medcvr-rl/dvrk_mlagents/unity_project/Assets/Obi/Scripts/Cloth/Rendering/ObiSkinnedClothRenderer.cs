using UnityEngine;
using System.Collections;
using System.Collections.Generic;
using System;

namespace Obi
{
    [AddComponentMenu("Physics/Obi/Obi Skinned Cloth Renderer", 905)]
    [RequireComponent(typeof(SkinnedMeshRenderer))]
    [ExecuteInEditMode]
    public class ObiSkinnedClothRenderer : ObiClothRendererBase, ObiActorRenderer<ObiSkinnedClothRenderer>
    {

        [Header("Bind parameters")]
        public float radius = 0.25f;
        public float falloff = 1;
        public uint maxInfluences = 4;

        public ObiSkinnedCloth cloth;
        public ObiSkinMap customSkinMap;

        public override ObiActor actor
        {
            get { return cloth; }
        }

        public override Material[] materials
        {
            get { return skinnedMeshRenderer.sharedMaterials; }
        }

        private SkinnedMeshRenderer skinnedMeshRenderer;

        protected Transform[] m_Bones = new Transform[0];

        /*public override Matrix4x4 renderMatrix
        {
            get
            {
                var skinScale = Matrix4x4.Scale(skinnedMeshRenderer.transform.lossyScale);
                return skinScale * skinnedMeshRenderer.transform.worldToLocalMatrix;
            }
        }*/

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
            sourceRenderer = skinnedMeshRenderer = GetComponent<SkinnedMeshRenderer>();
            m_Bones = skinnedMeshRenderer.bones;

            // In case there's no user-set cloth reference,
            // try to find one in the same object:
            if (cloth == null)
                cloth = GetComponent<ObiSkinnedCloth>();
        }

        public void CleanupRenderer()
        {
            skinnedMeshRenderer.sharedMesh = sourceMesh;
        }

        public override bool ValidateRenderer()
        {
            if (skinnedMeshRenderer == null)
                sourceRenderer = skinnedMeshRenderer = GetComponent<SkinnedMeshRenderer>();

            // no shared mesh, no custom skinmap, use the blueprint's input mesh:
            if (skinnedMeshRenderer.sharedMesh == null && customSkinMap == null && actor.sharedBlueprint != null)
                skinnedMeshRenderer.sharedMesh = ((ObiClothBlueprint)actor.sharedBlueprint).inputMesh;

            // if there's a sharedMesh, store it.
            if (skinnedMeshRenderer.sharedMesh != null)
                sourceMesh = skinnedMeshRenderer.sharedMesh;

            // at runtime, set the sharedMesh to null since we will be doing our own rendering.
            if (Application.isPlaying)
                skinnedMeshRenderer.sharedMesh = null;

            bool valid = base.ValidateRenderer();
            valid &= skinMap.bonesOnParticles.influenceOffsets.count == actor.particleCount + 1;

            return valid;
        }

        public void OnEnable()
        {
             ((ObiActorRenderer<ObiSkinnedClothRenderer>)this).EnableRenderer();
        }

        public void OnDisable()
        {
             ((ObiActorRenderer<ObiSkinnedClothRenderer>)this).DisableRenderer();
        }

        public void OnValidate()
        {
            ((ObiActorRenderer<ObiSkinnedClothRenderer>)this).SetRendererDirty(Oni.RenderingSystemType.SkinnedCloth);
        }

        RenderSystem<ObiSkinnedClothRenderer> ObiRenderer<ObiSkinnedClothRenderer>.CreateRenderSystem(ObiSolver solver)
        {
            switch (solver.backendType)
            {

#if (OBI_BURST && OBI_MATHEMATICS && OBI_COLLECTIONS)
                case ObiSolver.BackendType.Burst: return new BurstSkinnedClothRenderSystem(solver);
#endif
                case ObiSolver.BackendType.Compute:
                default:

                    if (SystemInfo.supportsComputeShaders)
                        return new ComputeSkinnedClothRenderSystem(solver);
                    return null;
            }
        }

        public override void Bind()
        {
            if (skinMap != null && cloth.clothBlueprintBase != null)
            {
                skinnedMeshRenderer = GetComponent<SkinnedMeshRenderer>();
                var blueprintTransform = transform.gameObject == cloth.gameObject ? Matrix4x4.TRS(Vector3.zero, cloth.clothBlueprintBase.rotation, cloth.clothBlueprintBase.scale) : Matrix4x4.identity;

                skinMap.MapBonesToParticles(skinnedMeshRenderer.sharedMesh, topology, transform.localToWorldMatrix, cloth.transform.worldToLocalMatrix);
                skinMap.MapParticlesToVertices(skinnedMeshRenderer.sharedMesh, cloth.clothBlueprintBase, transform.localToWorldMatrix * blueprintTransform, cloth.transform.worldToLocalMatrix, radius, falloff, maxInfluences);
                skinMap.checksum = cloth.clothBlueprintBase.checksum;
            }
        }
    }
}