using UnityEngine;
using Obi;

// This script must be placed on the obi solver
[RequireComponent(typeof(ObiSolver))]
public class MultiCutDetector : MonoBehaviour
{
	// This is set automatically as the Agent already has a reference to the
	// solver
	[HideInInspector]
	public MultiCutAgent Agent;

	public float distanceThreshold = 0.001f;

	ObiSolver solver;

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
			(int index, ObiActor actor) = CutRope(bestJaw1Contact);
			if (index == -1) return;
			Agent.CutDetectedCallback(index, actor, MultiCutAgent.CutQuality.Best);
			return;
		}

		if (goodJaw1Contact > -1 && goodJaw2Contact > -1)
		{
			(int index, ObiActor actor) = CutRope(goodJaw1Contact);
			if (index == -1) return;
			Agent.CutDetectedCallback(index, actor, MultiCutAgent.CutQuality.Good);
			return;
		}

		if (badJaw1Contact > -1 && badJaw2Contact > -1)
        {
			(int index, ObiActor actor) = CutRope(badJaw1Contact);
			if (index == -1) return;
			Agent.CutDetectedCallback(index, actor, MultiCutAgent.CutQuality.Bad);
			return;
        }
	}

	(int, ObiActor) CutRope(int jawContactParticleIndex)
    {
		// Note: Here we assume that both jaws will have the same simplex contact and particle indices
		ObiSolver.ParticleInActor pa = solver.particleToActor[jawContactParticleIndex];
		var actor = pa.actor as ObiRope;
		
		if (actor == null) return (-1, null);
		int cutElementIndex = 0;

		// check rope elements and tear the one that references this particle:
		foreach (var elm in actor.elements)
		{
			if (elm.particle1 == jawContactParticleIndex)
			{
				cutElementIndex = actor.elements.IndexOf(elm);
				actor.Tear(elm);
				actor.RebuildConstraintsFromElements();
				break;
			}
		}

		return (cutElementIndex, actor);
	}
}
