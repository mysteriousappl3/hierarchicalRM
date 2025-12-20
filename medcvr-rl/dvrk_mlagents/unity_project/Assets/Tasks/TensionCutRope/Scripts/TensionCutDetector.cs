using UnityEngine;
using Obi;

[RequireComponent(typeof(ObiSolver))]
public class TensionCutDetector : MonoBehaviour
{
    [HideInInspector]
    public TensionCutRopeAgent Agent;

    public float distanceThreshold = 0.001f;

    ObiSolver solver;

    [HideInInspector]
    public bool GraspDetected = false;
    [HideInInspector]
    public bool CutDetected = false;

    void Awake()
    {
        solver = GetComponent<ObiSolver>();
    }

    void OnEnable()
    {
        solver.OnCollision += Solver_OnCollision;
    }

    void OnDisable()
    {
        solver.OnCollision -= Solver_OnCollision;
    }

    void Solver_OnCollision(object sender, ObiNativeContactList contacts)
    {
        if (CutDetected) return;
        var world = ObiColliderWorld.GetInstance();

        int jaw1Contact = -1;
        int jaw2Contact = -1;

        int bestJaw1Contact = -1;
        int bestJaw2Contact = -1;

        int badJaw1Contact = -1;
        int badJaw2Contact = -1;

        int goodJaw1Contact = -1;
        int goodJaw2Contact = -1;
        ObiColliderBase contactCollider = null;

        // just iterate over all contacts in the current frame:
        foreach (Oni.Contact contact in contacts)
        {
            if (contact.distance > distanceThreshold) continue;

            int simplexStart = solver.simplexCounts.GetSimplexStartAndSize(
                contact.bodyA, out int simplexSize);

            ObiColliderBase col = world.colliderHandles[contact.bodyB].owner;

            if (col == null) continue;

            if (col.gameObject.CompareTag("BestCutJaw1"))
            {
                // get the index of the particle involved in the contact:
                bestJaw1Contact = solver.simplices[simplexStart];
            }
            else if (col.gameObject.CompareTag("BestCutJaw2"))
            {
                // get the index of the particle involved in the contact:
                bestJaw2Contact = solver.simplices[simplexStart];
            }
            else if (col.gameObject.CompareTag("GoodCutJaw1"))
            {
                // get the index of the particle involved in the contact:
                goodJaw1Contact = solver.simplices[simplexStart];
            }
            else if (col.gameObject.CompareTag("GoodCutJaw2"))
            {
                // get the index of the particle involved in the contact:
                goodJaw2Contact = solver.simplices[simplexStart];
            }
            else if (col.gameObject.CompareTag("BadCutJaw1"))
            {
                // get the index of the particle involved in the contact:
                badJaw1Contact = solver.simplices[simplexStart];
            }
            else if (col.gameObject.CompareTag("BadCutJaw2"))
            {
                // get the index of the particle involved in the contact:
                badJaw2Contact = solver.simplices[simplexStart];
            }
            else if (col.gameObject.CompareTag("jaw1"))
            {
                // get the index of the particle involved in the contact:
                jaw1Contact = solver.simplices[simplexStart];
                contactCollider = col;
            }
            else if (col.gameObject.CompareTag("jaw2"))
            {
                // get the index of the particle involved in the contact:
                jaw2Contact = solver.simplices[simplexStart];
            }
        }

        if (jaw1Contact > -1 && jaw2Contact > -1)
        {
            if (!GraspDetected)
            {
                GraspDetected = true;
                ObiSolver.ParticleInActor pa = solver.particleToActor[jaw1Contact];
                if (pa == null) return;

                ObiRope ropeObject = pa.actor.GetComponent<ObiRope>();
                var ropeElements = ropeObject.elements;

                int graspElementIndex = 0;
                for (int j = 0; j < ropeElements.Count; j++)
                {
                    if (ropeElements[j].particle1 == jaw1Contact)
                    {
                        graspElementIndex = j;
                    }
                }
                PinRope(jaw1Contact, contactCollider);
                Agent.GraspDetectedCallback(graspElementIndex);
            }
        }
        else
        {
            if (GraspDetected)
            {
                UnpinRope();
                GraspDetected = false;
                Agent.GraspNotDetectedCallback();
            }
        }

        if (CutDetected) return;
        if (bestJaw1Contact > -1 && bestJaw2Contact > -1)
        {
            int index = CutRope(bestJaw1Contact);
            if (index == -1) return;
            Agent.CutDetectedCallback(index, TensionCutRopeAgent.CutQuality.Best);
        }
        else if (goodJaw1Contact > -1 && goodJaw2Contact > -1)
        {
            int index = CutRope(goodJaw1Contact);
            if (index == -1) return;
            Agent.CutDetectedCallback(index, TensionCutRopeAgent.CutQuality.Good);
        }
        else if (badJaw1Contact > -1 && badJaw2Contact > -1)
        {
            int index = CutRope(badJaw1Contact);
            if (index == -1) return;
            Agent.CutDetectedCallback(index, TensionCutRopeAgent.CutQuality.Bad);
        }
    }

    int CutRope(int jawContactParticleIndex)
    {
        CutDetected = true;

        // Note: Here we assums that both jaws will have the same simplex contact and particle indices
        ObiSolver.ParticleInActor pa = solver.particleToActor[jawContactParticleIndex];

        if (pa == null) return -1;

        ObiRope ropeObject = pa.actor.GetComponent<ObiRope>();
        var ropeElements = ropeObject.elements;

        // Note: If theres only 1 rope, then the ropeElement indicies match up with particle indices
        // but this is not the case with multiple ropes, so we loop to check the particle indices of this rope
        int cutElementIndex = 0;
        for (int j = 0; j < ropeElements.Count; j++)
        {
            if (ropeElements[j].particle1 == jawContactParticleIndex)
            {
                cutElementIndex = j;
                int particleToTear = ropeObject.elements[j].particle1;
                ropeObject.Tear(ropeElements[particleToTear]);
                ropeObject.RebuildConstraintsFromElements();
            }
        }

        return cutElementIndex;
    }

    void PinRope(int jawContactParticleIndex, ObiColliderBase col)
    {
        ObiSolver.ParticleInActor pa = solver.particleToActor[jawContactParticleIndex];
        ObiRope ropeObject = pa.actor.GetComponent<ObiRope>();

        var pinConstraints = ropeObject.GetConstraintsByType(
            Oni.ConstraintType.Pin) as ObiConstraints<ObiPinConstraintsBatch>;
        pinConstraints.Clear();
        var batch = new ObiPinConstraintsBatch();

        Vector3 colliderToToolMidpoint = Agent.LNDToolMidpoint.transform.position - col.transform.position;
        Vector3 particlePosition = ropeObject.GetParticlePosition(jawContactParticleIndex);
        Vector3 particleToMidpoint = Agent.LNDToolMidpoint.transform.position - particlePosition;

        Vector3 contactDelta = colliderToToolMidpoint - particleToMidpoint;
        contactDelta = col.transform.InverseTransformVector(contactDelta);

        batch.AddConstraint(
            jawContactParticleIndex,
            col,
            contactDelta, // new Vector3(0, 0, -0.001f),
            Quaternion.identity,
            0,
            0,
            float.PositiveInfinity);

        particlePosition = ropeObject.GetParticlePosition(jawContactParticleIndex + 1);
        particleToMidpoint = Agent.LNDToolMidpoint.transform.position - particlePosition;
        contactDelta = colliderToToolMidpoint - particleToMidpoint;
        contactDelta = col.transform.InverseTransformVector(contactDelta);

        batch.AddConstraint(
            jawContactParticleIndex + 1,
            col,
            contactDelta, // new Vector3(0, 0.002f, -0.001f),
            Quaternion.identity,
            0,
            0,
            float.PositiveInfinity);

        batch.activeConstraintCount = 2;
        // append the batch to the pin constraints:
        pinConstraints.AddBatch(batch);

        // this will cause the solver to rebuild pin constraints at the beginning of the next frame:
        ropeObject.SetConstraintsDirty(Oni.ConstraintType.Pin);

        // float thickness = DomainRandomizer.Instance.RandomizeDomain(ropeObject.solver.principalRadii[0].x, "rope_thickness");
        // ropeObject.solver.principalRadii[jawContactParticleIndex] = new Vector3(thickness, 0.01f, 0.01f);
        // ropeObject.solver.principalRadii[jawContactParticleIndex + 1] = new Vector3(thickness, 0.01f, 0.01f);
    }

    public void UnpinRope()
    {
        ObiSolver.ParticleInActor pa = solver.particleToActor[0];
        ObiRope ropeObject = pa.actor.GetComponent<ObiRope>();

        // Create a pin constraint at the grasp point with the tool
        var pinConstraints = ropeObject.GetConstraintsByType(
            Oni.ConstraintType.Pin) as ObiConstraints<ObiPinConstraintsBatch>;

        // remove all batches from it, so we start clean:
        pinConstraints.Clear();

        // this will cause the solver to rebuild pin constraints at the beginning of the next frame:
        ropeObject.SetConstraintsDirty(Oni.ConstraintType.Pin);

        // float thickness = DomainRandomizer.Instance.RandomizeDomain(ropeObject.solver.principalRadii[0].x, "rope_thickness");

        // for (int i = 0; i < ropeObject.solverIndices.Length; i++)
        // {
        //     int solverIndex = ropeObject.solverIndices[i];
        //     ropeObject.solver.principalRadii[solverIndex] = new Vector3(thickness, thickness, thickness);
        // }
    }
}
