using UnityEngine;
using Obi;

// This script must be placed on the obi solver
[RequireComponent(typeof(ObiSolver))]
public class CutDetector : MonoBehaviour
{
	// This is set automatically as the Agent already has a reference to the
	// solver
	[HideInInspector]
	public CutRopeAgent Agent;

	public float distanceThreshold = 0.001f;

	ObiSolver solver;

	// We only want the first detected cut, there might be multiple collisions
	// across multiple frames, lets avoid that
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

        int bestJaw1Contact = -1;
        int bestJaw2Contact = -1;

        int badJaw1Contact = -1;
        int badJaw2Contact = -1;

        int goodJaw1Contact = -1;
        int goodJaw2Contact = -1;

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
                bestJaw1Contact = solver.simplices[simplexStart];
            }
            else if (col.gameObject.CompareTag("BestCutJaw2"))
            {
                bestJaw2Contact = solver.simplices[simplexStart];
            }
            else if (col.gameObject.CompareTag("GoodCutJaw1"))
            {
                goodJaw1Contact = solver.simplices[simplexStart];
            }
            else if (col.gameObject.CompareTag("GoodCutJaw2"))
            {
                goodJaw2Contact = solver.simplices[simplexStart];
            }
            else if (col.gameObject.CompareTag("BadCutJaw1"))
            {
                badJaw1Contact = solver.simplices[simplexStart];
            }
            else if (col.gameObject.CompareTag("BadCutJaw2"))
            {
                badJaw2Contact = solver.simplices[simplexStart];
            }
        }

		// If Collision happens where two sets of colliders (e.g. Best and Good) both touch rope,
		// then we choose the better. This can be switched to do the opposite and act conservatively.
		if (bestJaw1Contact > -1 && bestJaw2Contact > -1)
		{
			int index = CutRope(bestJaw1Contact);
			if (index == -1) return;
			Agent.CutDetectedCallback(index, CutRopeAgent.CutQuality.Best);
			return;
		}

		if (goodJaw1Contact > -1 && goodJaw2Contact > -1)
		{
			int index = CutRope(goodJaw1Contact);
			if (index == -1) return;
			Agent.CutDetectedCallback(index, CutRopeAgent.CutQuality.Good);
			return;
		}

		if (badJaw1Contact > -1 && badJaw2Contact > -1)
        {
			int index = CutRope(badJaw1Contact);
			if (index == -1) return;
			Agent.CutDetectedCallback(index, CutRopeAgent.CutQuality.Bad);
			return;
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
}
