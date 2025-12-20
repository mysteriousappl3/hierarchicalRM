using UnityEngine;
using UnityEditor;
using System.Collections;

namespace Obi
{
    public class ObiBlueprintSkinBackstopRadius : ObiBlueprintFloatProperty
    {

        public ObiBlueprintSkinBackstopRadius(ObiActorBlueprintEditor editor) : base(editor,0)
        {
            brushModes.Add(new ObiFloatPaintBrushMode(this));
            brushModes.Add(new ObiFloatAddBrushMode(this));
            brushModes.Add(new ObiFloatCopyBrushMode(this, this));
            brushModes.Add(new ObiFloatSmoothBrushMode(this));
        }

        public override string name
        {
            get { return "Skin backstop radius"; }
        }

        public override float Get(int index)
        {
            var constraints = editor.blueprint.GetConstraintsByType(Oni.ConstraintType.Skin) as ObiConstraints<ObiSkinConstraintsBatch>;
            return constraints.batches[0].skinRadiiBackstop[index * 3 + 1];
        }
        public override void Set(int index, float value)
        {
            var constraints = editor.blueprint.GetConstraintsByType(Oni.ConstraintType.Skin) as ObiConstraints<ObiSkinConstraintsBatch>;
            constraints.batches[0].skinRadiiBackstop[index * 3 + 1] = value;
            editor.blueprint.edited = true;
        }
        public override bool Masked(int index)
        {
            return !editor.Editable(index);
        }

        public override void OnSceneRepaint()
        {
            var meshEditor = editor as ObiMeshBasedActorBlueprintEditor;
            if (meshEditor != null)
            {
                using (new Handles.DrawingScope(Color.red, Matrix4x4.identity))
                {
                    var constraints = meshEditor.blueprint.GetConstraintsByType(Oni.ConstraintType.Skin) as ObiConstraints<ObiSkinConstraintsBatch>;
                    if (constraints != null)
                    {
                        var batches = constraints.batches;
                        foreach (ObiSkinConstraintsBatch batch in batches)
                        {
                            for (int i = 0; i < batch.activeConstraintCount; ++i)
                            {
                                int particleIndex = batch.particleIndices[i];
                                if (meshEditor.visible[particleIndex])
                                {
                                    Vector3 position = meshEditor.blueprint.GetParticlePosition(particleIndex);
                                    Quaternion restOrientation = meshEditor.blueprint.GetParticleRestOrientation(particleIndex);
                                    Vector3 normal = restOrientation* Vector3.forward;

                                    float backstop = batch.skinRadiiBackstop[i * 3 + 2];
                                    float radius = backstop + batch.skinRadiiBackstop[i * 3 + 1];

                                    Handles.DrawLine(position - normal * backstop, 
                                                     position - normal * radius);
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
