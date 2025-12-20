using UnityEngine;
using Unity.Profiling;
using System.Collections;
using System.Collections.Generic;

namespace Obi
{
    [AddComponentMenu("Physics/Obi/Obi SkinnedCloth", 902)]
    [RequireComponent(typeof(SkinnedMeshRenderer))]
    public class ObiSkinnedCloth : ObiClothBase, ITetherConstraintsUser, ISkinConstraintsUser
    {
        [SerializeField] protected ObiSkinnedClothBlueprint m_SkinnedClothBlueprint;

        // tethers
        [SerializeField] protected bool _tetherConstraintsEnabled = true;
        [SerializeField] protected float _tetherCompliance = 0;
        [SerializeField] [Range(0.1f, 2)] protected float _tetherScale = 1;

        public override ObiActorBlueprint sourceBlueprint
        {
            get { return m_SkinnedClothBlueprint; }
        }

        public override ObiClothBlueprintBase clothBlueprintBase
        {
            get { return m_SkinnedClothBlueprint; }
        }

        /// <summary>  
        /// Whether this actor's tether constraints are enabled.
        /// </summary>
        public bool tetherConstraintsEnabled
        {
            get { return _tetherConstraintsEnabled; }
            set { if (value != _tetherConstraintsEnabled) { _tetherConstraintsEnabled = value; SetConstraintsDirty(Oni.ConstraintType.Tether); } }
        }

        /// <summary>  
        /// Compliance of this actor's tether constraints.
        /// </summary>
        public float tetherCompliance
        {
            get { return _tetherCompliance; }
            set { _tetherCompliance = value; SetConstraintsDirty(Oni.ConstraintType.Tether); }
        }

        /// <summary>  
        /// Rest length scaling for this actor's tether constraints.
        /// </summary>
        public float tetherScale
        {
            get { return _tetherScale; }
            set { _tetherScale = value; SetConstraintsDirty(Oni.ConstraintType.Tether); }
        }

        public bool skinConstraintsEnabled { get { return true; } set { } }

        public ObiSkinnedClothBlueprint skinnedClothBlueprint
        {
            get { return m_SkinnedClothBlueprint; }
            set
            {
                if (m_SkinnedClothBlueprint != value)
                {
                    RemoveFromSolver();
                    ClearState();
                    m_SkinnedClothBlueprint = value;
                    AddToSolver();
                }
            }
        }

        private SkinnedMeshRenderer skin;
        [HideInInspector] public List<Vector3> bakedVertices = new List<Vector3>();
        [HideInInspector] public List<Vector3> bakedNormals = new List<Vector3>();
        [HideInInspector] public List<Vector4> bakedTangents = new List<Vector4>();

        protected override void OnValidate()
        {
            base.OnValidate();
            SetupRuntimeConstraints();
        }

        private void SetupRuntimeConstraints()
        {
            SetConstraintsDirty(Oni.ConstraintType.Distance);
            SetConstraintsDirty(Oni.ConstraintType.Bending);
            SetConstraintsDirty(Oni.ConstraintType.Aerodynamics);
            SetConstraintsDirty(Oni.ConstraintType.Tether);
            SetSelfCollisions(m_SelfCollisions);
            SetSimplicesDirty();
        }

        protected override void OnEnable()
        {
            base.OnEnable();
            skin = GetComponent<SkinnedMeshRenderer>();
        }

        protected override void OnDisable()
        {
            base.OnDisable();

            if (m_SkinnedClothBlueprint != null)
                skin.sharedMesh = m_SkinnedClothBlueprint.inputMesh;
        }

        public Vector3 GetSkinRadiiBackstop(ObiSkinConstraintsBatch batch, int constraintIndex)
        {
            return new Vector3(batch.skinRadiiBackstop[constraintIndex*3],
                               batch.skinRadiiBackstop[constraintIndex * 3+1],
                               batch.skinRadiiBackstop[constraintIndex * 3+2]);
        }

        public float GetSkinCompliance(ObiSkinConstraintsBatch batch, int constraintIndex)
        {
            return batch.skinCompliance[constraintIndex];
        }

    }

}