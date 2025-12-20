using UnityEngine;
using Obi;
using System;
using System.Collections.Generic;

[RequireComponent(typeof(ObiSolver))]
public class RopeGraspDetector : MonoBehaviour
{
    private ObiSolver solver;

    public float distanceThreshold = 0.01f;

    [HideInInspector]
	public TensionRopeAgent Agent;

	[HideInInspector]
	public bool GraspDetected = false;

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
        var world = ObiColliderWorld.GetInstance();
        int jaw1Contact = -1;
		int jaw2Contact = -1;
        ObiColliderBase contactCollider = null;

        foreach (Oni.Contact contact in contacts)
		{
			// if this one is an actual collision:
			if (contact.distance < distanceThreshold)
			{
                ObiColliderBase col = world.colliderHandles[contact.bodyB].owner;
                int simplexStart = solver.simplexCounts.GetSimplexStartAndSize(
					contact.bodyA, out int simplexSize);
				if (col != null && col.gameObject.CompareTag("jaw1"))
				{
					// get the index of the particle involved in the contact:
					jaw1Contact = solver.simplices[simplexStart];
                    contactCollider = col;
				}
				else if (col != null && col.gameObject.CompareTag("jaw2"))
                {
					// get the index of the particle involved in the contact:
					jaw2Contact = solver.simplices[simplexStart];
				}
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
    }

    void PinRope(int jawContactParticleIndex, ObiColliderBase col)
    {
        ObiSolver.ParticleInActor pa = solver.particleToActor[jawContactParticleIndex];
        ObiRope ropeObject = pa.actor.GetComponent<ObiRope>();

        var pinConstraints = ropeObject.GetConstraintsByType(
            Oni.ConstraintType.Pin) as ObiConstraints<ObiPinConstraintsBatch>;
        pinConstraints.Clear();
        var batch = new ObiPinConstraintsBatch();

        Vector3 colliderToToolMidpoint = Agent.ToolMidpoint.transform.position - col.transform.position;
        Vector3 particlePosition = ropeObject.GetParticlePosition(jawContactParticleIndex);
        Vector3 particleToMidpoint = Agent.ToolMidpoint.transform.position - particlePosition;

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
        particleToMidpoint = Agent.ToolMidpoint.transform.position - particlePosition;
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

    void UnpinRope()
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
