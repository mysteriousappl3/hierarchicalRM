using System.Collections.Generic;
using UnityEngine;
using Obi;

public class RaycastLasers : MonoBehaviour
{
    public ObiSolver solver;
    public LineRenderer[] lasers;
    int filter;

    List<QueryResult> raycastResults = new List<QueryResult>();

    private void Start()
    {
        filter = ObiUtils.MakeFilter(ObiUtils.CollideWithEverything, 0);
        solver.OnSpatialQueryResults += Solver_OnSpatialQueryResults;
        solver.OnSimulationStart += Solver_OnSimulate;
    }

    private void OnDestroy()
    {
        solver.OnSpatialQueryResults -= Solver_OnSpatialQueryResults;
        solver.OnSimulationStart -= Solver_OnSimulate;
    }

    private void Solver_OnSimulate(ObiSolver s, float timeToSimulate, float substepTime)
    {
        raycastResults.Clear();

        for (int i = 0; i < lasers.Length; ++i)
        {
            lasers[i].useWorldSpace = true;
            lasers[i].positionCount = 2;
            lasers[i].SetPosition(0, lasers[i].transform.position);

            solver.EnqueueRaycast(new Ray(lasers[i].transform.position, lasers[i].transform.up), filter, 20);
            raycastResults.Add(new QueryResult { distanceAlongRay = 20, simplexIndex = -1, queryIndex = -1 });
        }
    }

    private void Solver_OnSpatialQueryResults(ObiSolver s, ObiNativeQueryResultList queryResults)
    {
        for (int i = 0; i < queryResults.count; ++i)
        {
            if (queryResults[i].distanceAlongRay < raycastResults[queryResults[i].queryIndex].distanceAlongRay)
                raycastResults[queryResults[i].queryIndex] = queryResults[i];
        }

        for (int i = 0; i < raycastResults.Count; ++i)
        {
            lasers[i].SetPosition(1, lasers[i].transform.position + lasers[i].transform.up * raycastResults[i].distanceAlongRay);

            if (raycastResults[i].simplexIndex >= 0)
            {
                int simplexStartA = solver.simplexCounts.GetSimplexStartAndSize(raycastResults[i].simplexIndex, out int simplexSizeA);

                // Debug draw the simplex we hit (assuming it's a triangle):
                if (simplexSizeA == 3)
                {
                    Vector3 pos1 = solver.positions[solver.simplices[simplexStartA]];
                    Vector3 pos2 = solver.positions[solver.simplices[simplexStartA + 1]];
                    Vector3 pos3 = solver.positions[solver.simplices[simplexStartA + 2]];
                    Debug.DrawLine(pos1, pos2, Color.yellow);
                    Debug.DrawLine(pos2, pos3, Color.yellow);
                    Debug.DrawLine(pos3, pos1, Color.yellow);
                }

                lasers[i].startColor = Color.red;
                lasers[i].endColor = Color.red;
            }
            else
            {
                lasers[i].startColor = Color.blue;
                lasers[i].endColor = Color.blue;
            }
        }
    }
}